"""Real independent SQLite connections reproduce the session-start queue lock."""

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from sqlalchemy import event, select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.engine.memory_rag import dirty_queue, scheduling, worker
from backend.engine.memory_rag.sqlite_busy import is_sqlite_busy
from backend.models.avatar import Avatar
from backend.models.base import Base
from backend.models.game_session import GameSession
from backend.models.memory_rag import MemoryIndexState
from backend.models.user import User


@pytest.fixture
async def sqlite_file(tmp_path, monkeypatch):
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'locked.db'}", connect_args={"timeout": 0.05}
    )

    @event.listens_for(engine.sync_engine, "connect")
    def wal(connection, _):
        cursor = connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions() as db:
        db.add(User(id="owner", username="queue-owner", hashed_password="test"))
        db.add(Avatar(id="avatar", user_id="owner", name="Hero"))
        await db.flush()
        db.add(GameSession(id="session", user_id="owner", avatar_id="avatar"))
        await db.commit()
    monkeypatch.setattr(worker.database, "AsyncSessionLocal", sessions)
    monkeypatch.setattr(scheduling, "scheduler", scheduling.IdleScheduler(grace_seconds=0))
    monkeypatch.setattr(dirty_queue, "RETRY_INITIAL_SECONDS", 0.01)
    monkeypatch.setattr(worker, "schedule", MagicMock())
    try:
        yield sessions
    finally:
        await dirty_queue.shutdown()
        await engine.dispose()


async def test_stream_finishes_while_startup_writer_holds_lock_then_queue_retries(
    sqlite_file, monkeypatch
):
    busy, scheduled = asyncio.Event(), asyncio.Event()
    real_update = worker.request_update
    attempts = 0

    async def update_queue(*args):
        nonlocal attempts
        attempts += 1
        try:
            await real_update(*args)
        except Exception as exc:
            if is_sqlite_busy(exc):
                busy.set()
            raise

    monkeypatch.setattr(worker, "request_update", update_queue)
    monkeypatch.setattr(worker, "schedule", lambda *_: scheduled.set())
    manager = SimpleNamespace(
        state=SimpleNamespace(session_id="session"), user=SimpleNamespace(id="owner")
    )

    @scheduling.foreground_turn
    async def stream(manager):
        yield "final"

    async with sqlite_file() as startup:
        await startup.execute(
            update(GameSession)
            .where(GameSession.id == "session")
            .values(adventure_title="Initialized")
        )
        iterator = stream(manager)
        assert await anext(iterator) == "final"
        with pytest.raises(StopAsyncIteration):
            await asyncio.wait_for(anext(iterator), 0.2)
        assert scheduling.scheduler.active_turns == 0
        await asyncio.wait_for(busy.wait(), 3)
        assert not scheduled.is_set()
        await startup.commit()
    await asyncio.wait_for(scheduled.wait(), 3)
    async with sqlite_file() as db:
        row = await db.get(MemoryIndexState, "session")
        assert row is not None and row.desired_revision == 1
        assert (await db.get(GameSession, "session")).adventure_title == "Initialized"
    assert attempts >= 2


async def test_busy_dirty_mark_defers_without_committing_or_rolling_back_caller(
    sqlite_file, monkeypatch
):
    queue = MagicMock()
    monkeypatch.setattr(dirty_queue, "queue_refresh", queue)
    async with sqlite_file() as other, sqlite_file() as caller:
        await other.execute(update(GameSession).values(adventure_title="Committed elsewhere"))
        await worker.mark_dirty(caller, "session", "owner", None)
        queue.assert_called_once_with("session", "owner")
        assert caller.in_transaction()
        await other.commit()
        await caller.rollback()
    async with sqlite_file() as db:
        assert await db.scalar(select(MemoryIndexState)) is None
        assert (await db.get(GameSession, "session")).adventure_title == "Committed elsewhere"
