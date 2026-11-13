"""Actual SQL processing boundaries with source extraction replaced by controlled fixtures."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import NAMESPACE_URL, uuid5

import pytest
from sqlalchemy import func, select, update

from backend.engine.world_info import jobs, queue, worker
from backend.engine.world_info.types import (
    EntryDraft,
    Evidence,
    Fact,
    entry_content_hash,
    entry_search_text,
)
from backend.models.chat import ChatMessage
from backend.models.game_session import GameSession
from backend.models.world_info import WorldInfoEntry, WorldInfoRevision, WorldInfoSource
from tests.conftest import TestSessionLocal
from tests.test_world_info_extraction import proposal
from tests.test_world_info_jobs import portrait_world, seed_revision, world_info_owner

__all__ = ["portrait_world", "world_info_owner"]


def fixture_entry(revision_id, source_hash, batch):
    passage = batch.passages[0]
    quote = passage.text[:20]
    return EntryDraft(
        id=str(uuid5(NAMESPACE_URL, f"entry:{revision_id}:{batch.index}")),
        title=f"Archive fact {batch.index}",
        facts=[
            Fact(
                id=str(uuid5(NAMESPACE_URL, f"fact:{revision_id}:{batch.index}")),
                text="The archive has a documented custom.",
                original_text="The archive has a documented custom.",
                evidence=[
                    Evidence(
                        passage_id=passage.id,
                        pointer=passage.pointer,
                        start=passage.start,
                        end=passage.start + len(quote),
                        quote=quote,
                        source_hash=source_hash,
                    )
                ],
            )
        ],
    )


async def test_uploaded_review_or_copied_draft_does_not_start_model_work(
    world_info_owner, monkeypatch
):
    await seed_revision(world_info_owner, status="uploaded")
    extract = AsyncMock()
    schedule = MagicMock()
    monkeypatch.setattr(worker, "extract_batch", extract)
    monkeypatch.setattr(worker, "schedule", schedule)
    await worker.recover_pending()
    await worker._run("portrait-session", world_info_owner)
    schedule.assert_not_called()
    extract.assert_not_awaited()


async def test_failure_resume_reuses_validated_batches_and_freezes_language(
    world_info_owner, monkeypatch, caplog
):
    owner = world_info_owner
    revision_id = await seed_revision(owner, content="X" * 17000)
    calls = []
    fail = True

    async def extract(user, sid, rid, source_hash, batch, references, **kwargs):
        await kwargs["before_request"]()
        calls.append((batch.index, kwargs["language"]))
        if fail and batch.index == 1:
            raise ConnectionError("private fixture response must not enter operational logs")
        return [fixture_entry(rid, source_hash, batch)]

    monkeypatch.setattr(worker, "extract_batch", extract)
    await worker._run("portrait-session", owner)
    async with TestSessionLocal() as db:
        row = await db.get(WorldInfoRevision, revision_id)
        assert (row.status, row.cursor, row.entries_count, row.facts_count, row.attempts) == (
            "failed",
            1,
            1,
            1,
            2,
        )
        entry = await db.scalar(select(WorldInfoEntry))
        entry.title = "Reviewed draft title"
        entry.version += 1
        entry.edited = True
        edited = EntryDraft(
            id=entry.id,
            title=entry.title,
            summary=entry.summary,
            facts=entry.facts,
            tags=entry.tags,
            relations=entry.relations,
            kind=entry.kind,
        )
        entry.search_text = entry_search_text(edited)
        entry.content_hash = entry_content_hash(edited)
        session = await db.get(GameSession, "portrait-session")
        session.content_language = "Arabic"
        await db.commit()
        await jobs.start_processing(db, owner, "portrait-session", revision_id, row.control_version)
        await db.commit()
    fail = False
    await worker._run("portrait-session", owner)
    async with TestSessionLocal() as db:
        row = await db.get(WorldInfoRevision, revision_id)
        assert row.status == "review" and row.cursor == row.total_batches == 3
        assert row.entries_count == row.facts_count == 3 and row.attempts == 4
        assert row.processed_characters == row.input_characters == 17000
        entries = list(
            await db.scalars(select(WorldInfoEntry).order_by(WorldInfoEntry.batch_index))
        )
        assert entries[0].title == "Reviewed draft title" and entries[0].version == 2
        assert all(
            entry.status == "draft" and entry.audience == "narrator_only" for entry in entries
        )
        assert (await db.scalar(select(WorldInfoSource))).published_revision is None
        assert await db.scalar(select(func.count(ChatMessage.id))) == 0
    assert calls == [(0, "Russian"), (1, "Russian"), (1, "Russian"), (2, "Russian")]
    assert "private fixture response" not in caplog.text


async def test_cancel_while_model_waits_preserves_attempt_and_prevents_draft_write(
    world_info_owner, monkeypatch
):
    owner = world_info_owner
    revision_id = await seed_revision(owner)
    started = asyncio.Event()

    async def extract(*args, **kwargs):
        await kwargs["before_request"]()
        started.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(worker, "extract_batch", extract)
    claim = await queue.claim_next("portrait-session", owner)
    task = asyncio.create_task(worker.process_claim(claim))
    await asyncio.wait_for(started.wait(), 1)
    async with TestSessionLocal() as db:
        await jobs.cancel_processing(db, owner, "portrait-session", revision_id, 1)
        await db.commit()
    worker.cancel_local(revision_id)
    await asyncio.wait_for(task, 1)
    async with TestSessionLocal() as db:
        row = await db.get(WorldInfoRevision, revision_id)
        assert row.status == "cancelled" and row.attempts == 1 and row.cursor == 0
        assert await db.scalar(select(func.count(WorldInfoEntry.id))) == 0


@pytest.mark.parametrize("change", ["replace", "delete"])
async def test_late_model_response_cannot_save_after_source_changes(
    world_info_owner, monkeypatch, change
):
    owner = world_info_owner
    revision_id = await seed_revision(owner)
    started, finish = asyncio.Event(), asyncio.Event()

    async def extract(user, sid, rid, source_hash, batch, references, **kwargs):
        await kwargs["before_request"]()
        started.set()
        await finish.wait()
        return [fixture_entry(rid, source_hash, batch)]

    monkeypatch.setattr(worker, "extract_batch", extract)
    claim = await queue.claim_next("portrait-session", owner)
    task = asyncio.create_task(worker.process_claim(claim))
    await asyncio.wait_for(started.wait(), 1)
    async with TestSessionLocal() as db:
        source = await db.get(WorldInfoSource, claim.source_id)
        await jobs.fence_source(db, owner, "portrait-session", source.id)
        if change == "replace":
            source.current_revision = 2
        else:
            await db.delete(source)
        await db.commit()
    finish.set()
    await asyncio.wait_for(task, 1)
    async with TestSessionLocal() as db:
        assert await db.scalar(select(func.count(WorldInfoEntry.id))) == 0
        row = await db.get(WorldInfoRevision, revision_id)
        assert row is None or row.status == "cancelled"


async def test_empty_extraction_is_reviewable_completed_work(world_info_owner, monkeypatch):
    revision_id = await seed_revision(world_info_owner)

    async def extract(*args, **kwargs):
        await kwargs["before_request"]()
        return []

    monkeypatch.setattr(worker, "extract_batch", extract)
    await worker._run("portrait-session", world_info_owner)
    async with TestSessionLocal() as db:
        row = await db.get(WorldInfoRevision, revision_id)
        assert row.status == "review" and row.cursor == row.total_batches == 1
        assert row.facts_count == row.entries_count == 0 and row.attempts == 1


async def test_shutdown_retains_completed_batch_and_restart_recovers_only_pending_work(
    world_info_owner, monkeypatch
):
    owner = world_info_owner
    revision_id = await seed_revision(owner, content="X" * 9000)
    second_started = asyncio.Event()

    async def extract(user, sid, rid, source_hash, batch, references, **kwargs):
        await kwargs["before_request"]()
        if batch.index:
            second_started.set()
            await asyncio.Event().wait()
        return [fixture_entry(rid, source_hash, batch)]

    monkeypatch.setattr(worker, "extract_batch", extract)
    worker.schedule("portrait-session", owner)
    await asyncio.wait_for(second_started.wait(), 1)
    await worker.shutdown()
    assert not worker._tasks and not worker._active and not worker._timers
    async with TestSessionLocal() as db:
        row = await db.get(WorldInfoRevision, revision_id)
        assert row.status == "queued" and row.cursor == row.entries_count == 1
        assert row.attempts == 2 and row.lease_token is None
    schedule = MagicMock()
    monkeypatch.setattr(worker, "schedule", schedule)
    await worker.recover_pending()
    schedule.assert_called_once_with("portrait-session", owner)


async def test_actual_extractor_counts_correction_and_keeps_safe_call_context(
    world_info_owner, monkeypatch
):
    owner = world_info_owner
    revision_id = await seed_revision(owner, content="The lighthouse overlooks the harbour.")
    router = SimpleNamespace(
        model="fictional-test-model",
        max_tokens=10000,
        aexecute_complex_task=AsyncMock(side_effect=[ValueError("invalid schema"), proposal()]),
    )
    monkeypatch.setattr(
        "backend.engine.world_info.extraction.GameMasterLLM.for_role", lambda *_: router
    )
    await worker._run("portrait-session", owner)
    assert router.aexecute_complex_task.await_count == 2
    for call in router.aexecute_complex_task.call_args_list:
        assert call.kwargs["adventure_id"] is None
        assert call.kwargs["game_id"] == "portrait-session"
        assert "Russian" in call.kwargs["system_prompt"]
    async with TestSessionLocal() as db:
        row = await db.get(WorldInfoRevision, revision_id)
        assert row.status == "review" and row.attempts == 2 and row.facts_count == 1


async def test_cancellation_before_correction_prevents_another_model_request(
    world_info_owner, monkeypatch
):
    owner = world_info_owner
    revision_id = await seed_revision(owner, content="The lighthouse overlooks the harbour.")

    async def reject_after_cancel(**kwargs):
        async with TestSessionLocal() as db:
            await jobs.cancel_processing(db, owner, "portrait-session", revision_id, 1)
            await db.commit()
        raise ValueError("invalid schema")

    router = SimpleNamespace(
        model="fictional-test-model",
        max_tokens=10000,
        aexecute_complex_task=AsyncMock(side_effect=reject_after_cancel),
    )
    monkeypatch.setattr(
        "backend.engine.world_info.extraction.GameMasterLLM.for_role", lambda *_: router
    )
    await worker._run("portrait-session", owner)
    router.aexecute_complex_task.assert_awaited_once()
    async with TestSessionLocal() as db:
        row = await db.get(WorldInfoRevision, revision_id)
        assert row.status == "cancelled" and row.attempts == 1 and row.cursor == 0


async def test_saved_counts_preserve_draft_deletion_during_next_model_request(
    world_info_owner, monkeypatch
):
    owner = world_info_owner
    revision_id = await seed_revision(owner, content="X" * 9000)

    async def extract(user, sid, rid, source_hash, batch, references, **kwargs):
        await kwargs["before_request"]()
        if batch.index:
            async with TestSessionLocal() as db:
                old = await db.scalar(select(WorldInfoEntry))
                await db.delete(old)
                await db.execute(
                    update(WorldInfoRevision)
                    .where(WorldInfoRevision.id == rid)
                    .values(
                        facts_count=WorldInfoRevision.facts_count - 1,
                        entries_count=WorldInfoRevision.entries_count - 1,
                    )
                )
                await db.commit()
        return [fixture_entry(rid, source_hash, batch)]

    monkeypatch.setattr(worker, "extract_batch", extract)
    await worker._run("portrait-session", owner)
    async with TestSessionLocal() as db:
        row = await db.get(WorldInfoRevision, revision_id)
        assert row.status == "review" and row.cursor == row.total_batches == 2
        assert row.facts_count == row.entries_count == 1
        entry = await db.scalar(select(WorldInfoEntry))
        assert entry.batch_index == 1
