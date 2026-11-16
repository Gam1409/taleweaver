"""Durable source processing never promotes drafts or accepts stale workers."""

from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select

from backend.engine.memory_rag import scheduling
from backend.engine.world_info import jobs, queue, worker
from backend.engine.world_info.parsing import parse_source
from backend.models.game_session import GameSession
from backend.models.world_info import WorldInfoRevision, WorldInfoSource
from tests.conftest import TestSessionLocal
from tests.test_session_portraits import portrait_world

__all__ = ["portrait_world"]


@pytest_asyncio.fixture
async def world_info_owner(portrait_world, monkeypatch):
    monkeypatch.setattr(scheduling, "scheduler", scheduling.IdleScheduler(grace_seconds=0))
    async with TestSessionLocal() as db:
        session = await db.get(GameSession, "portrait-session")
        session.content_language = "Russian"
        await db.commit()
        owner = session.user_id
    yield owner
    await worker.shutdown()


async def seed_revision(
    owner: str,
    *,
    status: str = "queued",
    content: str = "The archive opens at dawn.",
    session_id: str = "portrait-session",
    session_factory=TestSessionLocal,
) -> str:
    plan = parse_source(content, "md")
    async with session_factory() as db:
        source = WorldInfoSource(
            user_id=owner,
            session_id=session_id,
            title="Archive notes",
            filename="notes.md",
            format="md",
        )
        db.add(source)
        await db.flush()
        revision = WorldInfoRevision(
            source_id=source.id,
            user_id=owner,
            session_id=source.session_id,
            number=1,
            filename=source.filename,
            format="md",
            content=content,
            content_hash=plan.source_hash,
            input_bytes=plan.bytes,
            input_characters=plan.characters,
            status=status,
            run_token=str(uuid4()) if status == "queued" else None,
            processing_language="Russian" if status == "queued" else None,
            total_batches=len(plan.batches) if status == "queued" else 0,
        )
        db.add(revision)
        await db.commit()
        return revision.id


async def test_claim_is_exclusive_and_cancel_fences_the_existing_worker(world_info_owner):
    owner = world_info_owner
    revision_id = await seed_revision(owner)
    claim = await queue.claim_next("portrait-session", owner)
    assert claim and claim.revision_id == revision_id
    assert await queue.claim_next("portrait-session", owner) is None
    async with TestSessionLocal() as db:
        row = await db.get(WorldInfoRevision, revision_id)
        await jobs.cancel_processing(
            db, owner, "portrait-session", revision_id, row.control_version
        )
        await db.commit()
    assert not await queue.release(claim, status="review")
    async with TestSessionLocal() as db:
        row = await db.get(WorldInfoRevision, revision_id)
        assert row.status == "cancelled"
        assert row.run_token is row.lease_token is None
        assert row.cursor == row.facts_count == row.entries_count == row.attempts == 0


async def test_claim_rejects_foreign_owner_and_replaced_source_revision(world_info_owner):
    owner = world_info_owner
    revision_id = await seed_revision(owner)
    assert await queue.claim_next("portrait-session", "foreign") is None
    async with TestSessionLocal() as db:
        source = await db.scalar(select(WorldInfoSource))
        source.current_revision = 2
        await db.commit()
    assert await queue.claim_next("portrait-session", owner) is None
    async with TestSessionLocal() as db:
        row = await db.get(WorldInfoRevision, revision_id)
        assert row.lease_token is None


async def test_control_compare_and_set_rejects_duplicate_or_stale_cancel(world_info_owner):
    owner = world_info_owner
    revision_id = await seed_revision(owner)
    async with TestSessionLocal() as db:
        await jobs.cancel_processing(db, owner, "portrait-session", revision_id, 1)
        await db.commit()
        with pytest.raises(jobs.JobConflictError):
            await jobs.cancel_processing(db, owner, "portrait-session", revision_id, 1)
        await db.rollback()
        with pytest.raises(jobs.JobNotFoundError):
            await jobs.cancel_processing(db, "foreign", "portrait-session", revision_id, 2)


async def test_start_freezes_language_and_resume_preserves_progress(world_info_owner):
    owner = world_info_owner
    content = "X" * 9000
    revision_id = await seed_revision(owner, status="uploaded", content=content)
    async with TestSessionLocal() as db:
        row = await jobs.start_processing(db, owner, "portrait-session", revision_id, 1)
        await db.commit()
        assert row.processing_language == "Russian"
        first_run = row.run_token
        assert row.total_batches == len(parse_source(row.content, "md").batches)
        with pytest.raises(jobs.JobConflictError):
            await jobs.start_processing(db, owner, "portrait-session", revision_id, 2)
        await db.rollback()
        await jobs.cancel_processing(db, owner, "portrait-session", revision_id, 2)
        row.cursor = 1
        completed_characters = sum(
            len(passage.text) for passage in parse_source(content, "md").batches[0].passages
        )
        row.processed_characters = completed_characters
        row.attempts = 2
        session = await db.get(GameSession, "portrait-session")
        session.content_language = "Arabic"
        await db.commit()
        resumed = await jobs.start_processing(db, owner, "portrait-session", revision_id, 3)
        await db.commit()
        assert resumed.processing_language == "Russian"
        assert resumed.run_token != first_run
        assert (resumed.cursor, resumed.processed_characters, resumed.attempts) == (
            1,
            completed_characters,
            2,
        )


async def test_expired_lease_takeover_rejects_old_dispatch_and_save(world_info_owner):
    owner = world_info_owner
    revision_id = await seed_revision(owner)
    old = await queue.claim_next("portrait-session", owner)
    async with TestSessionLocal() as db:
        row = await db.get(WorldInfoRevision, revision_id)
        row.lease_until = 0
        await db.commit()
    new = await queue.claim_next("portrait-session", owner)
    assert old and new and old.lease_token != new.lease_token
    with pytest.raises(queue.StaleJobError):
        await queue.reserve_request(old)
    assert not await queue.release(old, status="review")
    await queue.reserve_request(new)
    async with TestSessionLocal() as db:
        row = await db.get(WorldInfoRevision, revision_id)
        assert row.lease_token == new.lease_token and row.attempts == 1


@pytest.mark.parametrize(
    "field,value",
    [
        ("content_hash", "0" * 64),
        ("parser_version", 99),
        ("processing_language", "unsupported"),
        ("processed_characters", -1),
    ],
)
async def test_start_rejects_invalid_saved_input_without_replacing_it(
    world_info_owner, field, value
):
    owner = world_info_owner
    revision_id = await seed_revision(owner, status="uploaded")
    async with TestSessionLocal() as db:
        row = await db.get(WorldInfoRevision, revision_id)
        setattr(row, field, value)
        await db.commit()
        with pytest.raises(jobs.JobConflictError):
            await jobs.start_processing(db, owner, "portrait-session", revision_id, 1)
        await db.rollback()
        await db.refresh(row)
        assert row.status == "uploaded" and row.control_version == 1 and row.attempts == 0
        assert getattr(row, field) == value
