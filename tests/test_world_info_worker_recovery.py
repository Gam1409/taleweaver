"""Queued source intent recovers from exhausted operational SQLite contention."""

import asyncio
import json
import sqlite3
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import text, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.engine.memory_rag import persistence, scheduling
from backend.engine.memory_rag.sqlite_busy import is_sqlite_busy
from backend.engine.world_info import jobs, queue, sources, worker
from backend.models.avatar import Avatar
from backend.models.base import Base
from backend.models.game_session import GameSession
from backend.models.user import User
from backend.models.world_info import WorldInfoRevision
from tests.test_world_info_extraction import proposal

SID = "recovery-session"
OWNER = "recovery-owner"


@pytest.fixture
async def recovery_store(tmp_path, monkeypatch):
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'recovery.db'}", connect_args={"timeout": 0.01}
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(worker.database, "AsyncSessionLocal", sessions)
    monkeypatch.setattr(scheduling, "scheduler", scheduling.IdleScheduler(grace_seconds=0))
    monkeypatch.setattr(persistence, "RETRY_DELAYS", (0.02,))
    try:
        yield sessions
    finally:
        await worker.shutdown()
        await engine.dispose()


@pytest.fixture
async def pending_source(recovery_store, monkeypatch):
    def response(**kwargs):
        passage = json.loads(kwargs["user_prompt"])["passages"][0]
        result = proposal(passage["text"][:60])
        result["facts"][0]["evidence"][0]["passage_id"] = passage["id"]
        return result

    router = SimpleNamespace(
        model="fictional-recovery-model",
        max_tokens=6144,
        aexecute_complex_task=AsyncMock(side_effect=response),
    )
    monkeypatch.setattr(
        "backend.engine.world_info.extraction.GameMasterLLM.for_role", lambda *_: router
    )
    async with recovery_store() as db:
        db.add(User(id=OWNER, username=OWNER, hashed_password="fixture"))
        db.add(Avatar(id="recovery-avatar", user_id=OWNER, name="Hero"))
        await db.flush()
        db.add(GameSession(id=SID, user_id=OWNER, avatar_id="recovery-avatar"))
        await db.commit()
        content = "".join(
            f"Archive custom {i:04}: keep this numbered document safely.\n" for i in range(180)
        )
        _, revision, _ = await sources.upload(
            db, OWNER, SID, filename="notes.md", content=content, format="md"
        )
        await db.commit()
        await jobs.start_processing(db, OWNER, SID, revision.id, 1)
        await db.commit()
        rid = revision.id
    claim = await queue.claim_next(SID, OWNER)
    await worker.process_claim(claim)
    async with recovery_store() as db:
        revision = await db.get(WorldInfoRevision, rid)
        assert revision.status == "queued" and revision.cursor == revision.attempts == 1
        token = revision.run_token
    return rid, token, router.aexecute_complex_task


async def wait_for_review(sessions, revision_id):
    async with asyncio.timeout(3):
        while True:
            async with sessions() as db:
                revision = await db.get(WorldInfoRevision, revision_id)
                if revision.status == "review":
                    return revision
            await asyncio.sleep(0.01)


async def test_exhausted_claim_contention_reschedules_without_replaying_completed_work(
    recovery_store, pending_source, monkeypatch
):
    rid, token, model = pending_source
    exhausted = asyncio.Event()
    original = queue.claim_next

    async def claim(*args):
        try:
            return await original(*args)
        except Exception as error:
            if is_sqlite_busy(error):
                exhausted.set()
            raise

    monkeypatch.setattr(queue, "claim_next", claim)
    async with recovery_store() as writer:
        await writer.execute(
            update(GameSession)
            .where(GameSession.id == SID)
            .values(adventure_title="Concurrent edit")
        )
        worker.schedule(SID, OWNER)
        task = worker._tasks[SID]
        await asyncio.wait_for(exhausted.wait(), 3)
        await asyncio.wait({task}, timeout=1)
        assert SID in worker._timers
        async with recovery_store() as db:
            revision = await db.get(WorldInfoRevision, rid)
            assert (revision.status, revision.cursor, revision.attempts, revision.run_token) == (
                "queued",
                1,
                1,
                token,
            )
        assert model.await_count == 1
        await writer.commit()
    revision = await wait_for_review(recovery_store, rid)
    assert revision.cursor == revision.attempts == model.await_count == revision.total_batches


async def test_busy_retry_lookup_recovers_expired_lease_without_replaying_saved_batches(
    recovery_store, pending_source, monkeypatch
):
    rid, token, model = pending_source
    async with recovery_store() as db:
        revision = await db.get(WorldInfoRevision, rid)
        revision.status = "processing"
        revision.lease_token = "previous-worker"
        revision.lease_until = time.time() + 60
        await db.commit()
    original = queue.claim_next
    blocked = asyncio.Event()
    async with recovery_store() as writer:

        async def claim(*args):
            result = await original(*args)
            if result is None and not blocked.is_set():
                await writer.execute(text("BEGIN EXCLUSIVE"))
                await writer.execute(
                    update(WorldInfoRevision)
                    .where(WorldInfoRevision.id == rid)
                    .values(lease_until=0)
                )
                blocked.set()
            return result

        monkeypatch.setattr(queue, "claim_next", claim)
        worker.schedule(SID, OWNER)
        task = worker._tasks[SID]
        await asyncio.wait_for(blocked.wait(), 3)
        await asyncio.wait({task}, timeout=1)
        assert SID in worker._timers
        assert model.await_count == 1
        await writer.commit()
    revision = await wait_for_review(recovery_store, rid)
    assert revision.cursor == revision.attempts == model.await_count == revision.total_batches
    assert token is not None


@pytest.mark.parametrize("operation", ["claim", "retry_lookup"])
async def test_nonbusy_queue_errors_are_not_retried(recovery_store, monkeypatch, operation):
    failure = sqlite3.OperationalError("disk I/O error")
    claim = AsyncMock(side_effect=failure) if operation == "claim" else AsyncMock(return_value=None)
    retry = AsyncMock(side_effect=failure)
    monkeypatch.setattr(queue, "claim_next", claim)
    monkeypatch.setattr(worker, "_next_retry", retry)
    with pytest.raises(sqlite3.OperationalError, match="disk I/O"):
        await worker._run(SID, OWNER)
    claim.assert_awaited_once()
    assert not worker._timers


async def test_processing_errors_do_not_enter_operational_queue_retry(recovery_store, monkeypatch):
    claim = AsyncMock(return_value=object())
    process = AsyncMock(side_effect=sqlite3.OperationalError("database is locked"))
    monkeypatch.setattr(queue, "claim_next", claim)
    monkeypatch.setattr(worker, "process_claim", process)
    with pytest.raises(sqlite3.OperationalError, match="database is locked"):
        await worker._run(SID, OWNER)
    claim.assert_awaited_once()
    process.assert_awaited_once()
    assert not worker._timers


@pytest.mark.parametrize("action", ["cancel", "shutdown"])
async def test_deferred_retry_respects_durable_cancel_and_shutdown(
    recovery_store, pending_source, monkeypatch, action
):
    rid, token, model = pending_source
    original = queue.claim_next
    claim = AsyncMock(side_effect=sqlite3.OperationalError("database is locked"))
    monkeypatch.setattr(queue, "claim_next", claim)
    worker.schedule(SID, OWNER)
    await asyncio.gather(worker._tasks[SID], return_exceptions=True)
    assert SID in worker._timers
    if action == "cancel":
        async with recovery_store() as db:
            revision = await db.get(WorldInfoRevision, rid)
            await jobs.cancel_processing(db, OWNER, SID, rid, revision.control_version)
            await db.commit()
        monkeypatch.setattr(queue, "claim_next", original)
        await asyncio.sleep(0.05)
    else:
        await worker.shutdown()
    assert not worker._tasks and not worker._timers and not worker._wakeups
    assert model.await_count == 1
    async with recovery_store() as db:
        revision = await db.get(WorldInfoRevision, rid)
        assert revision.cursor == revision.attempts == 1
        assert revision.status == ("cancelled" if action == "cancel" else "queued")
        assert revision.run_token == (None if action == "cancel" else token)
