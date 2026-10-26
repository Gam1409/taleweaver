"""Maintenance claim and release recover from a real competing SQLite writer."""

import asyncio

import pytest
from sqlalchemy import event, update

from backend.engine.memory_rag import persistence, worker
from backend.models.game_session import GameSession
from backend.models.memory_rag import MemoryIndexState
from tests.test_memory_queue_sqlite_contention import sqlite_file

__all__ = ["sqlite_file"]


@pytest.mark.parametrize("operation", ["claim", "release", "failure"])
async def test_worker_transactions_retry_competing_writer(sqlite_file, monkeypatch, operation):
    monkeypatch.setattr(persistence, "RETRY_DELAYS", (0.01, 0.02, 0.04))
    async with sqlite_file() as db:
        db.add(MemoryIndexState(session_id="session", user_id="owner"))
        await db.commit()
    claim = None if operation == "claim" else await worker._claim("session", "owner")
    busy = asyncio.Event()
    engine = sqlite_file.kw["bind"].sync_engine

    def on_error(context):
        if worker.is_sqlite_busy(context.original_exception):
            busy.set()

    event.listen(engine, "handle_error", on_error)
    try:
        async with sqlite_file() as other:
            await other.execute(update(GameSession).values(adventure_title="Concurrent turn"))
            action = worker._claim("session", "owner")
            if operation != "claim":
                action.close()
                action = (
                    worker._release(claim)
                    if operation == "release"
                    else worker._record_failure(claim, 60)
                )
            task = asyncio.create_task(action)
            await asyncio.wait_for(busy.wait(), 3)
            assert not task.done()
            await other.commit()
        result = await asyncio.wait_for(task, 3)
        async with sqlite_file() as db:
            row = await db.get(MemoryIndexState, "session")
            if operation == "claim":
                assert result is not None and row.lease_token == result.token
            else:
                assert row.lease_token is None
            if operation == "failure":
                assert row.status == "error"
    finally:
        event.remove(engine, "handle_error", on_error)


async def test_background_save_waits_outside_transaction_for_active_turn(monkeypatch):
    from unittest.mock import AsyncMock

    from backend.engine.memory_rag import scheduling

    gate = scheduling.IdleScheduler(grace_seconds=0)
    monkeypatch.setattr(scheduling, "scheduler", gate)
    operation = AsyncMock(return_value="saved")
    async with gate.foreground():
        pending = asyncio.create_task(persistence.retry_transaction(operation)())
        await asyncio.sleep(0)
        operation.assert_not_awaited()
    assert await asyncio.wait_for(pending, 1) == "saved"
    operation.assert_awaited_once()


@pytest.mark.parametrize("takeover", [False, True])
async def test_expired_claim_can_finish_only_until_reclaimed(sqlite_file, takeover):
    async with sqlite_file() as db:
        db.add(MemoryIndexState(session_id="session", user_id="owner"))
        await db.commit()
    old = await worker._claim("session", "owner")
    async with sqlite_file() as db:
        await db.execute(update(MemoryIndexState).values(lease_until=0))
        await db.commit()
    new = await worker._claim("session", "owner") if takeover else None
    await worker._release(old, status="ready")
    async with sqlite_file() as db:
        row = await db.get(MemoryIndexState, "session")
        assert row.lease_token == (new.token if new else None)
        assert row.status == ("pending" if new else "ready")
