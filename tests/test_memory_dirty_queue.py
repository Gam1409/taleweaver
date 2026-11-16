"""Deferred queue intents coalesce, retry outside transactions and drain on shutdown."""

import asyncio
import sqlite3
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.exc import OperationalError

from backend.engine.memory_rag import dirty_queue, scheduling, worker
from backend.engine.memory_rag.sqlite_busy import is_sqlite_busy


def busy(code=sqlite3.SQLITE_BUSY):
    error = sqlite3.OperationalError("database is locked")
    error.sqlite_errorcode = code
    return OperationalError("UPDATE memory_index_states", {}, error)


@pytest.fixture(autouse=True)
async def isolated_queue(monkeypatch):
    await dirty_queue.shutdown()
    monkeypatch.setattr(scheduling, "scheduler", scheduling.IdleScheduler(grace_seconds=0))
    yield
    await dirty_queue.shutdown()


async def drain():
    async with asyncio.timeout(2):
        while dirty_queue._pending:
            tasks = [job.task for job in dirty_queue._pending.values() if job.task is not None]
            await asyncio.gather(*tasks)
            await asyncio.sleep(0)


async def test_queue_returns_immediately_and_waits_for_foreground_release(monkeypatch):
    update = AsyncMock()
    monkeypatch.setattr(worker, "request_update", update)
    async with scheduling.scheduler.foreground():
        dirty_queue.queue_refresh("session", "owner")
        dirty_queue.queue_refresh("session", "owner")
        await asyncio.sleep(0)
        update.assert_not_awaited()
        assert len(dirty_queue._pending) == 1
    await drain()
    update.assert_awaited_once_with("session", "owner")


async def test_intent_during_attempt_is_not_lost_and_is_coalesced(monkeypatch):
    started, release = asyncio.Event(), asyncio.Event()
    calls = []

    async def update(session, owner):
        calls.append((session, owner))
        if len(calls) == 1:
            started.set()
            await release.wait()

    monkeypatch.setattr(worker, "request_update", update)
    dirty_queue.queue_refresh("session", "owner")
    await asyncio.wait_for(started.wait(), 1)
    dirty_queue.queue_refresh("session", "owner")
    dirty_queue.queue_refresh("session", "owner")
    release.set()
    await drain()
    assert calls == [("session", "owner"), ("session", "owner")]


async def test_intent_between_task_completion_and_callback_is_retained(monkeypatch):
    callbacks = []
    finish = dirty_queue._finish
    monkeypatch.setattr(dirty_queue, "_finish", lambda *args: callbacks.append(args))
    update = AsyncMock()
    monkeypatch.setattr(worker, "request_update", update)
    dirty_queue.queue_refresh("session", "owner")
    await dirty_queue._pending[("session", "owner")].task
    await asyncio.sleep(0)
    assert callbacks
    dirty_queue.queue_refresh("session", "owner")
    monkeypatch.setattr(dirty_queue, "_finish", finish)
    finish(*callbacks[0])
    await drain()
    assert update.await_count == 2


async def test_busy_retries_only_after_attempt_and_gate_have_closed(monkeypatch):
    calls = 0
    inside_transaction = False
    delays = []

    async def update(session, owner):
        nonlocal calls, inside_transaction
        calls += 1
        inside_transaction = True
        try:
            if calls <= 2:
                raise busy(sqlite3.SQLITE_BUSY_SNAPSHOT)
        finally:
            inside_transaction = False

    async def backoff(failures):
        assert not inside_transaction
        assert not scheduling.scheduler.capacity.locked()
        delays.append(failures)
        await asyncio.sleep(0)

    monkeypatch.setattr(worker, "request_update", update)
    monkeypatch.setattr(dirty_queue, "_wait_retry", backoff)
    dirty_queue.queue_refresh("session", "owner")
    await drain()
    assert calls == 3
    assert delays == [1, 2]


async def test_non_lock_failure_is_not_retried(monkeypatch):
    update = AsyncMock(side_effect=RuntimeError("not a database lock"))
    backoff, log = AsyncMock(), MagicMock()
    monkeypatch.setattr(worker, "request_update", update)
    monkeypatch.setattr(dirty_queue, "_wait_retry", backoff)
    monkeypatch.setattr(dirty_queue.logger, "exception", log)
    dirty_queue.queue_refresh("session", "owner")
    await drain()
    update.assert_awaited_once()
    backoff.assert_not_awaited()
    log.assert_called_once()


async def test_shutdown_cancels_retry_and_does_not_recreate_jobs(monkeypatch):
    retry_started = asyncio.Event()

    async def backoff(failures):
        retry_started.set()
        try:
            await asyncio.Event().wait()
        finally:
            # A callback cannot enqueue new work while shutdown is draining tasks.
            dirty_queue.queue_refresh("another-session", "owner")

    monkeypatch.setattr(worker, "request_update", AsyncMock(side_effect=busy()))
    monkeypatch.setattr(dirty_queue, "_wait_retry", backoff)
    dirty_queue.queue_refresh("session", "owner")
    task = dirty_queue._pending[("session", "owner")].task
    await asyncio.wait_for(retry_started.wait(), 1)
    await dirty_queue.shutdown()
    assert task.cancelled()
    assert not dirty_queue._pending
    assert not scheduling.scheduler.capacity.locked()


async def test_owner_scopes_do_not_merge_queue_intents(monkeypatch):
    update = AsyncMock()
    monkeypatch.setattr(worker, "request_update", update)
    dirty_queue.queue_refresh("session", "owner-one")
    dirty_queue.queue_refresh("session", "owner-two")
    await drain()
    assert update.await_count == 2
    update.assert_any_await("session", "owner-one")
    update.assert_any_await("session", "owner-two")


@pytest.mark.parametrize(
    "code", [sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED, sqlite3.SQLITE_BUSY_SNAPSHOT]
)
def test_sqlite_busy_primary_and_extended_codes(code):
    assert is_sqlite_busy(busy(code))


@pytest.mark.parametrize(
    "error",
    [
        RuntimeError("database is locked"),
        sqlite3.OperationalError("no such table: memory_index_states"),
        OperationalError("UPDATE", {}, ValueError("database is locked")),
        busy(sqlite3.SQLITE_ERROR),
    ],
)
def test_other_errors_are_not_contention(error):
    assert not is_sqlite_busy(error)


def test_old_sqlite_driver_without_numeric_code_uses_conservative_fallback():
    assert is_sqlite_busy(sqlite3.OperationalError("database table is locked: memory_index_states"))


async def test_retry_delay_grows_and_is_capped(monkeypatch):
    sleep = AsyncMock()
    with monkeypatch.context() as patch:
        patch.setattr(dirty_queue.asyncio, "sleep", sleep)
        await dirty_queue._wait_retry(1)
        await dirty_queue._wait_retry(2)
        await dirty_queue._wait_retry(1000)
    assert [call.args[0] for call in sleep.await_args_list] == [0.5, 1.0, 30.0]


async def test_cancelling_an_active_attempt_releases_gate_without_logging_failure(monkeypatch):
    entered = asyncio.Event()

    async def update(session, owner):
        entered.set()
        await asyncio.Event().wait()

    log = MagicMock()
    monkeypatch.setattr(worker, "request_update", update)
    monkeypatch.setattr(dirty_queue.logger, "exception", log)
    dirty_queue.queue_refresh("session", "owner")
    task = dirty_queue._pending[("session", "owner")].task
    await asyncio.wait_for(entered.wait(), 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await asyncio.sleep(0)
    assert not dirty_queue._pending
    assert not scheduling.scheduler.capacity.locked()
    log.assert_not_called()


async def test_gate_failure_does_not_restart_the_task_forever(monkeypatch):
    log = MagicMock()
    monkeypatch.setattr(dirty_queue.logger, "exception", log)
    monkeypatch.setattr(
        scheduling.scheduler,
        "background",
        MagicMock(side_effect=RuntimeError("scheduler unavailable")),
    )
    update = AsyncMock()
    monkeypatch.setattr(worker, "request_update", update)
    dirty_queue.queue_refresh("session", "owner")
    await drain()
    update.assert_not_awaited()
    log.assert_called_once()
