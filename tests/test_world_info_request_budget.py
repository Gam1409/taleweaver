"""Lifetime logical request budgets preserve saved progress and legacy portability."""

import asyncio
import sqlite3
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.llm_output_errors import StructuredOutputError
from backend.engine.world_info import jobs, limits, queue, sources, worker
from backend.engine.world_info.parsing import parse_source
from backend.engine.world_info.portability import copy_world_info, export_world_info
from backend.engine.world_info.view_records import job_record
from backend.models.game_session import GameSession
from backend.models.world_info import WorldInfoEntry, WorldInfoRevision, WorldInfoSource
from tests.conftest import TestSessionLocal
from tests.test_world_info_extraction import proposal
from tests.test_world_info_jobs import portrait_world, seed_revision, world_info_owner

__all__ = ["portrait_world", "world_info_owner"]
SID = "portrait-session"
CONTENT = "The lighthouse overlooks the harbour."


@pytest.fixture
def model(monkeypatch):
    router = SimpleNamespace(
        model="fictional-budget-model",
        max_tokens=10000,
        aexecute_complex_task=AsyncMock(return_value=proposal()),
    )
    monkeypatch.setattr(
        "backend.engine.world_info.extraction.GameMasterLLM.for_role", lambda *_: router
    )
    return router.aexecute_complex_task


async def set_attempts(revision_id, attempts, *, total_batches=None):
    async with TestSessionLocal() as db:
        row = await db.get(WorldInfoRevision, revision_id)
        row.attempts = attempts
        if total_batches is not None:
            row.total_batches = total_batches
        await db.commit()


async def test_final_allowed_request_saves_valid_output_at_exact_budget(world_info_owner, model):
    rid = await seed_revision(world_info_owner, content=CONTENT)
    await set_attempts(rid, 3)
    await worker._run(SID, world_info_owner)
    async with TestSessionLocal() as db:
        row = await db.get(WorldInfoRevision, rid)
        assert (row.status, row.cursor, row.entries_count, row.attempts) == ("review", 1, 1, 4)
        assert await db.scalar(select(func.count(WorldInfoEntry.id))) == 1
    model.assert_awaited_once()


async def test_correction_beyond_budget_stops_before_transport(world_info_owner, model):
    rid = await seed_revision(world_info_owner, content=CONTENT)
    await set_attempts(rid, 3)
    model.side_effect = StructuredOutputError("fictional malformed response")
    await worker._run(SID, world_info_owner)
    async with TestSessionLocal() as db:
        row = await db.get(WorldInfoRevision, rid)
        assert (row.status, row.cursor, row.attempts, row.last_error_code) == (
            "failed",
            0,
            4,
            "request_limit",
        )
        assert row.run_token is row.lease_token is None
        source = await db.get(WorldInfoSource, row.source_id)
        view = job_record(row, source, (0, 0))
        assert view.request_limit == 4 and not view.can_resume
        with pytest.raises(jobs.JobConflictError, match="budget"):
            await jobs.start_processing(db, world_info_owner, SID, rid, row.control_version)
    model.assert_awaited_once()


async def test_repeated_manual_resume_cannot_reset_lifetime_budget(world_info_owner, model):
    rid = await seed_revision(world_info_owner, status="uploaded", content=CONTENT)
    model.side_effect = StructuredOutputError("fictional malformed response")
    for expected in (2, 4):
        async with TestSessionLocal() as db:
            row = await db.get(WorldInfoRevision, rid)
            await jobs.start_processing(db, world_info_owner, SID, rid, row.control_version)
            await db.commit()
        await worker._run(SID, world_info_owner)
        async with TestSessionLocal() as db:
            row = await db.get(WorldInfoRevision, rid)
            assert row.status == "failed" and row.attempts == expected
    async with TestSessionLocal() as db:
        row = await db.get(WorldInfoRevision, rid)
        version = row.control_version
        with pytest.raises(jobs.JobConflictError, match="budget"):
            await jobs.start_processing(db, world_info_owner, SID, rid, version)
        await db.rollback()
        await db.refresh(row)
        assert row.attempts == 4 and row.control_version == version and row.run_token is None
    assert model.await_count == 4


async def test_final_reservation_commit_retry_is_idempotent(world_info_owner, monkeypatch):
    rid = await seed_revision(world_info_owner, content=CONTENT)
    await set_attempts(rid, 3)
    claim = await queue.claim_next(SID, world_info_owner)
    original = AsyncSession.commit
    interrupted = False

    async def commit_then_error(db):
        nonlocal interrupted
        await original(db)
        if not interrupted:
            interrupted = True
            raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(AsyncSession, "commit", commit_then_error)
    await queue.reserve_request(claim)
    with pytest.raises(queue.RequestBudgetError):
        await queue.reserve_request(claim, ordinal=1)
    async with TestSessionLocal() as db:
        row = await db.get(WorldInfoRevision, rid)
        assert row.attempts == 4 and row.lease_token == claim.lease_token
    assert interrupted


async def test_cancel_at_budget_preserves_attempts_and_blocks_resume(world_info_owner, model):
    rid = await seed_revision(world_info_owner, content=CONTENT)
    await set_attempts(rid, 3)
    started = asyncio.Event()

    async def wait_for_cancel(**kwargs):
        started.set()
        await asyncio.Event().wait()

    model.side_effect = wait_for_cancel
    claim = await queue.claim_next(SID, world_info_owner)
    task = asyncio.create_task(worker.process_claim(claim))
    await asyncio.wait_for(started.wait(), 1)
    async with TestSessionLocal() as db:
        row = await db.get(WorldInfoRevision, rid)
        await jobs.cancel_processing(db, world_info_owner, SID, rid, row.control_version)
        await db.commit()
    worker.cancel_local(rid)
    await asyncio.wait_for(task, 1)
    async with TestSessionLocal() as db:
        row = await db.get(WorldInfoRevision, rid)
        source = await db.get(WorldInfoSource, row.source_id)
        assert row.status == "cancelled" and row.attempts == 4 and row.cursor == 0
        assert not job_record(row, source, (0, 0)).can_resume
        with pytest.raises(jobs.JobConflictError, match="budget"):
            await jobs.start_processing(db, world_info_owner, SID, rid, row.control_version)
    model.assert_awaited_once()


@pytest.mark.parametrize("attempts", [4, 9])
async def test_expired_lease_recovery_at_budget_never_submits_inference(
    world_info_owner, model, attempts
):
    rid = await seed_revision(world_info_owner, content=CONTENT)
    await set_attempts(rid, attempts)
    old = await queue.claim_next(SID, world_info_owner)
    async with TestSessionLocal() as db:
        row = await db.get(WorldInfoRevision, rid)
        row.lease_until = 0
        await db.commit()
    await worker.recover_pending()
    await asyncio.gather(worker._tasks[SID])
    async with TestSessionLocal() as db:
        row = await db.get(WorldInfoRevision, rid)
        assert (row.status, row.cursor, row.attempts, row.last_error_code) == (
            "failed",
            0,
            attempts,
            "request_limit",
        )
        assert row.run_token is row.lease_token is None
    assert not await queue.release(old)
    model.assert_not_awaited()


async def test_known_and_unknown_job_budgets_keep_legacy_attempts_readable(world_info_owner):
    rid = await seed_revision(world_info_owner, status="failed", content="X" * 9000)
    await set_attempts(rid, 5)
    async with TestSessionLocal() as db:
        row = await db.get(WorldInfoRevision, rid)
        source = await db.get(WorldInfoSource, row.source_id)
        view = job_record(row, source, (0, 0))
        assert view.request_limit is None and view.can_resume
        legacy = type(view).model_validate(view.model_dump(exclude={"request_limit"}))
        assert legacy.request_limit is None and legacy.can_resume
        await jobs.start_processing(db, world_info_owner, SID, rid, row.control_version)
        await db.commit()
        assert row.total_batches == len(parse_source(row.content, "md").batches)
        assert job_record(row, source, (0, 0)).request_limit == 4 * row.total_batches
        assert row.attempts == 5


async def test_legacy_unknown_queued_job_stops_then_manual_resume_fixes_metadata(
    world_info_owner, model
):
    rid = await seed_revision(world_info_owner, content=CONTENT)
    await set_attempts(rid, 0, total_batches=0)
    await worker._run(SID, world_info_owner)
    model.assert_not_awaited()
    async with TestSessionLocal() as db:
        row = await db.get(WorldInfoRevision, rid)
        assert row.last_error_code == "request_limit" and row.attempts == row.cursor == 0
        await jobs.start_processing(db, world_info_owner, SID, rid, row.control_version)
        await db.commit()
        assert row.total_batches == 1
    await worker._run(SID, world_info_owner)
    model.assert_awaited_once()


async def test_high_legacy_attempts_survive_copy_and_dedup_without_budget_reset(world_info_owner):
    rid = await seed_revision(world_info_owner, status="failed", content=CONTENT)
    await set_attempts(rid, 9, total_batches=1)
    async with TestSessionLocal() as db:
        row = await db.get(WorldInfoRevision, rid)
        source = await db.get(WorldInfoSource, row.source_id)
        for operation in ("upload", "replace"):
            kwargs = dict(filename="notes.md", content=CONTENT, format="md")
            result = (
                await sources.upload(db, world_info_owner, SID, **kwargs)
                if operation == "upload"
                else await sources.replace(
                    db, world_info_owner, SID, source.id, source.version, **kwargs
                )
            )
            assert result[1].id == rid and result[1].attempts == 9 and result[2]
        await db.commit()
        db.add(GameSession(id="budget-copy", user_id=world_info_owner, avatar_id="portrait-avatar"))
        await db.flush()
        await copy_world_info(db, SID, "budget-copy", world_info_owner)
        await db.commit()
        copied = await export_world_info(db, "budget-copy", world_info_owner)
        assert copied["revisions"][0]["attempts"] == 9
        imported = await db.get(WorldInfoRevision, copied["revisions"][0]["id"])
        source = await db.get(WorldInfoSource, imported.source_id)
        assert job_record(imported, source, (0, 0)).request_limit == 4
        assert not job_record(imported, source, (0, 0)).can_resume
        with pytest.raises(jobs.JobConflictError, match="budget"):
            await jobs.start_processing(
                db, world_info_owner, "budget-copy", imported.id, imported.control_version
            )


async def test_schedule_during_lease_lookup_consumes_wakeup_and_replaces_lease_timer(
    world_info_owner, model, monkeypatch
):
    first = await seed_revision(world_info_owner, content=CONTENT)
    await queue.claim_next(SID, world_info_owner)
    entered, finish = asyncio.Event(), asyncio.Event()
    saved = asyncio.Event()
    original = worker._next_retry
    original_save = worker.save_batch

    async def lookup(*args):
        when = await original(*args)
        if not entered.is_set():
            entered.set()
            await finish.wait()
        return when

    monkeypatch.setattr(worker, "_next_retry", lookup)

    async def save(*args):
        result = await original_save(*args)
        assert result
        saved.set()
        return result

    monkeypatch.setattr(worker, "save_batch", save)
    worker.schedule(SID, world_info_owner)
    first_task = worker._tasks[SID]
    await asyncio.wait_for(entered.wait(), 1)
    second = await seed_revision(world_info_owner, content=CONTENT)
    worker.schedule(SID, world_info_owner)
    assert worker._wakeups[SID] == world_info_owner
    finish.set()
    await asyncio.gather(first_task)
    await asyncio.wait_for(saved.wait(), 2)
    async with TestSessionLocal() as db:
        row = await db.get(WorldInfoRevision, second)
        assert row.status == "review" and row.attempts == 1
        row = await db.get(WorldInfoRevision, first)
        assert row.status == "processing" and row.attempts == 0
    model.assert_awaited_once()


def test_named_packing_and_output_limits_preserve_current_policy():
    assert limits.MAX_OUTPUT_TOKENS == 6144
    assert limits.PACKED_PASSAGE_CHARACTERS == 3872
    plan = parse_source("X" * 8000, "md")
    passages = [p for batch in plan.batches for p in batch.passages]
    assert [(p.start, p.end) for p in passages] == [(0, 3872), (3872, 7744), (7744, 8000)]
