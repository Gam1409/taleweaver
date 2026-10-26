"""Request cancellation must not become a cache error or interrupt transaction cleanup."""

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import anyio
import pytest
from sqlalchemy import select

from backend.core import database
from backend.engine.memory_rag import scheduling, worker
from backend.engine.memory_rag.cancellation import find_cancellation
from backend.models.memory_rag import MemoryIndexState
from tests.conftest import TestSessionLocal
from tests.test_npc_journal import journal_world, portrait_world

__all__ = ["journal_world", "portrait_world"]


def manager():
    return SimpleNamespace(
        state=SimpleNamespace(session_id="session"), user=SimpleNamespace(id="owner")
    )


async def test_cancelled_stream_does_not_start_new_transaction(monkeypatch):
    scheduler = scheduling.IdleScheduler(grace_seconds=0)
    monkeypatch.setattr(scheduling, "scheduler", scheduler)
    update = AsyncMock()
    monkeypatch.setattr(worker, "request_update", update)

    @scheduling.foreground_turn
    async def stream(manager):
        yield "chunk"
        await anyio.lowlevel.checkpoint()

    with anyio.CancelScope() as scope:
        iterator = stream(manager())
        assert await anext(iterator) == "chunk"
        scope.cancel()
        with pytest.raises(asyncio.CancelledError):
            await anext(iterator)
    update.assert_not_awaited()
    assert scheduler.active_turns == 0


async def test_explicit_stream_close_does_not_queue_uncommitted_data(monkeypatch):
    scheduler = scheduling.IdleScheduler(grace_seconds=0)
    monkeypatch.setattr(scheduling, "scheduler", scheduler)
    update = AsyncMock()
    monkeypatch.setattr(worker, "request_update", update)

    @scheduling.foreground_turn
    async def stream(manager):
        yield "chunk"

    iterator = stream(manager())
    await anext(iterator)
    await iterator.aclose()
    update.assert_not_awaited()
    assert scheduler.active_turns == 0


async def test_savepoint_cleanup_error_preserves_original_cancellation(monkeypatch):
    cancelled = asyncio.CancelledError("request disconnected")

    @asynccontextmanager
    async def nested():
        try:
            yield
        except asyncio.CancelledError:
            raise ValueError("Connection closed") from None

    db = SimpleNamespace(begin_nested=nested)
    monkeypatch.setattr(worker, "_mark_dirty", AsyncMock(side_effect=cancelled))
    log = MagicMock()
    monkeypatch.setattr(worker.logger, "exception", log)
    with pytest.raises(asyncio.CancelledError) as caught:
        await worker.mark_dirty(db, "session", "owner", None)
    assert caught.value is cancelled
    log.assert_not_called()


async def test_queue_transaction_finishes_under_outer_cancellation(journal_world, monkeypatch):
    owner, _ = journal_world
    schedule = MagicMock()
    monkeypatch.setattr(worker, "schedule", schedule)
    with anyio.CancelScope() as scope:
        scope.cancel()
        await worker.request_update("portrait-session", owner)
        with pytest.raises(asyncio.CancelledError):
            await anyio.lowlevel.checkpoint()
    async with TestSessionLocal() as db:
        row = await db.scalar(
            select(MemoryIndexState).where(MemoryIndexState.session_id == "portrait-session")
        )
        assert row is not None and row.desired_revision == 1
    schedule.assert_called_once_with("portrait-session", owner)


async def test_raw_task_cancellation_never_commits_or_schedules(monkeypatch):
    db = SimpleNamespace(
        get=AsyncMock(return_value=SimpleNamespace(user_id="owner", template_id=None)),
        commit=AsyncMock(),
    )

    @asynccontextmanager
    async def factory():
        yield db

    monkeypatch.setattr(worker.database, "AsyncSessionLocal", factory)
    monkeypatch.setattr(worker, "mark_dirty", AsyncMock(side_effect=asyncio.CancelledError()))
    schedule = MagicMock()
    monkeypatch.setattr(worker, "schedule", schedule)
    with pytest.raises(asyncio.CancelledError):
        await worker.request_update("session", "owner")
    db.commit.assert_not_awaited()
    schedule.assert_not_called()


async def test_request_session_closes_under_cancelled_scope(monkeypatch):
    closed = False

    async def close():
        nonlocal closed
        await anyio.lowlevel.checkpoint()
        closed = True

    session = SimpleNamespace(close=close)

    @asynccontextmanager
    async def factory():
        yield session

    monkeypatch.setattr(database, "AsyncSessionLocal", factory)
    dependency = database.get_db()
    assert await anext(dependency) is session
    with anyio.CancelScope() as scope:
        scope.cancel()
        await dependency.aclose()
    assert closed


def test_cancellation_lookup_handles_wrapped_and_cyclic_errors():
    original = asyncio.CancelledError()
    outer = ValueError("closed")
    middle = RuntimeError("rollback")
    outer.__cause__ = middle
    middle.__context__ = original
    original.__context__ = outer
    assert find_cancellation(outer) is original
    outer.__cause__ = outer
    assert find_cancellation(outer) is None
