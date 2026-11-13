"""Independent SQLite writers and uncertain commits cannot repeat source extraction."""

import asyncio
import sqlite3
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import event, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.engine.memory_rag import persistence
from backend.engine.memory_rag.sqlite_busy import is_sqlite_busy
from backend.engine.world_info import queue, results, worker
from backend.models.game_session import GameSession
from backend.models.world_info import WorldInfoEntry, WorldInfoRevision
from tests.conftest import TestSessionLocal
from tests.test_memory_queue_sqlite_contention import sqlite_file
from tests.test_world_info_jobs import portrait_world, seed_revision, world_info_owner
from tests.test_world_info_worker import fixture_entry

__all__ = ["portrait_world", "sqlite_file", "world_info_owner"]


async def test_real_competing_writer_retries_saving_without_another_model_request(
    sqlite_file, monkeypatch
):
    revision_id = await seed_revision("owner", session_id="session", session_factory=sqlite_file)
    claim = await queue.claim_next("session", "owner")
    started, finish, busy = asyncio.Event(), asyncio.Event(), asyncio.Event()
    calls = []

    async def extract(user, sid, rid, source_hash, batch, references, **kwargs):
        await kwargs["before_request"]()
        calls.append(batch.index)
        started.set()
        await finish.wait()
        return [fixture_entry(rid, source_hash, batch)]

    monkeypatch.setattr(worker, "extract_batch", extract)
    monkeypatch.setattr(persistence, "RETRY_DELAYS", (0.01, 0.02, 0.04, 0.08))
    task = asyncio.create_task(worker.process_claim(claim))
    await asyncio.wait_for(started.wait(), 1)

    def on_error(context):
        if is_sqlite_busy(context.original_exception):
            busy.set()

    engine = sqlite_file.kw["bind"].sync_engine
    event.listen(engine, "handle_error", on_error)
    try:
        async with sqlite_file() as other:
            await other.execute(update(GameSession).values(adventure_title="Concurrent action"))
            finish.set()
            await asyncio.wait_for(busy.wait(), 3)
            assert not task.done()
            await other.commit()
        await asyncio.wait_for(task, 3)
    finally:
        event.remove(engine, "handle_error", on_error)
    async with sqlite_file() as db:
        row = await db.get(WorldInfoRevision, revision_id)
        assert row.status == "review" and row.cursor == row.attempts == row.entries_count == 1
        assert await db.scalar(select(func.count(WorldInfoEntry.id))) == 1
    assert calls == [0]


@pytest.mark.parametrize("phase", ["reservation", "result"])
async def test_uncertain_successful_commit_is_idempotent(world_info_owner, monkeypatch, phase):
    revision_id = await seed_revision(world_info_owner)
    calls = []
    original_commit = AsyncSession.commit
    original_capacity = results._check_capacity
    raised = False

    async def mark_result(db, claim, entries):
        await original_capacity(db, claim, entries)
        db.info["world_info_result"] = True

    async def commit_then_error(db):
        nonlocal raised
        await original_commit(db)
        is_result = bool(db.info.get("world_info_result"))
        if not raised and is_result == (phase == "result"):
            raised = True
            raise sqlite3.OperationalError("database is locked")

    async def extract(user, sid, rid, source_hash, batch, references, **kwargs):
        await kwargs["before_request"]()
        calls.append(batch.index)
        return [fixture_entry(rid, source_hash, batch)]

    monkeypatch.setattr(results, "_check_capacity", mark_result)
    monkeypatch.setattr(worker, "extract_batch", extract)
    monkeypatch.setattr(persistence, "RETRY_DELAYS", (0.001,))
    claim = await queue.claim_next("portrait-session", world_info_owner)
    monkeypatch.setattr(AsyncSession, "commit", commit_then_error)
    await worker.process_claim(claim)
    async with TestSessionLocal() as db:
        row = await db.get(WorldInfoRevision, revision_id)
        assert row.status == "review" and row.attempts == row.cursor == row.entries_count == 1
        assert await db.scalar(select(func.count(WorldInfoEntry.id))) == 1
    assert raised and calls == [0]


async def test_shutdown_cancellation_survives_cleanup_failure(world_info_owner, monkeypatch):
    await seed_revision(world_info_owner)
    claim = await queue.claim_next("portrait-session", world_info_owner)
    started = asyncio.Event()

    async def extract(*args, **kwargs):
        await kwargs["before_request"]()
        started.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(worker, "extract_batch", extract)
    task = asyncio.create_task(worker.process_claim(claim))
    await asyncio.wait_for(started.wait(), 1)
    monkeypatch.setattr(queue, "release", AsyncMock(side_effect=RuntimeError("cleanup failed")))
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    async with TestSessionLocal() as db:
        row = await db.get(WorldInfoRevision, claim.revision_id)
        assert row.cursor == 0 and row.attempts == 1
        assert await db.scalar(select(func.count(WorldInfoEntry.id))) == 0
