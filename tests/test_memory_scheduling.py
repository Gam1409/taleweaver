"""Foreground priority, bounded idle work, and durable fencing without model traffic."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.engine.memory_rag import scheduling, worker
from backend.engine.memory_rag.scheduling import IdleScheduler, foreground_turn
from backend.models.memory_rag import MemoryIndexState
from tests.conftest import TestSessionLocal
from tests.test_npc_journal import journal_world, portrait_world

__all__ = ["journal_world", "portrait_world"]


async def test_background_waits_for_foreground_and_full_quiet_grace(monkeypatch):
    clock = SimpleNamespace(now=100.0)
    monkeypatch.setattr(scheduling, "time", SimpleNamespace(monotonic=lambda: clock.now))
    scheduler = IdleScheduler(grace_seconds=15)
    started = asyncio.Event()

    async def background():
        async with scheduler.background():
            started.set()

    async with scheduler.foreground():
        task = asyncio.create_task(background())
        await asyncio.sleep(0)
        assert not started.is_set()
    clock.now = 114
    scheduler.changed.set()
    await asyncio.sleep(0)
    assert not started.is_set()
    clock.now = 115
    scheduler.changed.set()
    await asyncio.wait_for(task, 1)
    assert started.is_set()


async def test_foreground_never_waits_for_active_job_or_remaining_backlog():
    scheduler = IdleScheduler(grace_seconds=0)
    started, release = asyncio.Event(), asyncio.Event()
    calls = []

    async def backlog():
        for index in range(4):
            async with scheduler.background():
                calls.append(index)
                started.set()
                await release.wait()

    task = asyncio.create_task(backlog())
    await started.wait()
    async with scheduler.foreground():
        release.set()
        await asyncio.sleep(0)
        assert calls == [0]
        assert scheduler.active_turns == 1
    await asyncio.wait_for(task, 1)
    assert calls == [0, 1, 2, 3]


async def test_stream_failure_releases_foreground_and_queues_canonical_update(monkeypatch):
    scheduler = IdleScheduler(grace_seconds=0)
    monkeypatch.setattr(scheduling, "scheduler", scheduler)
    update = AsyncMock()
    monkeypatch.setattr(worker, "request_update", update)
    manager = SimpleNamespace(
        game_id="session",
        state=SimpleNamespace(session_id="session"),
        user=SimpleNamespace(id="owner"),
    )

    @foreground_turn
    async def stream(manager):
        assert scheduler.active_turns == 1
        yield "chunk"
        raise RuntimeError("turn failure")

    with pytest.raises(RuntimeError, match="turn failure"):
        async for _ in stream(manager):
            pass
    assert scheduler.active_turns == 0
    update.assert_awaited_once_with("session", "owner")


async def test_memory_database_failure_does_not_fail_foreground_stream(monkeypatch):
    scheduler = IdleScheduler(grace_seconds=0)
    monkeypatch.setattr(scheduling, "scheduler", scheduler)
    monkeypatch.setattr(
        worker.database,
        "AsyncSessionLocal",
        MagicMock(side_effect=RuntimeError("database offline")),
    )
    manager = SimpleNamespace(
        game_id="session",
        state=SimpleNamespace(session_id="session"),
        user=SimpleNamespace(id="owner"),
    )

    @foreground_turn
    async def stream(manager):
        yield "final"

    assert [chunk async for chunk in stream(manager)] == ["final"]
    assert scheduler.active_turns == 0


@pytest.mark.parametrize(
    ("state", "user"),
    [
        (None, SimpleNamespace(id="owner")),
        (SimpleNamespace(session_id="session"), SimpleNamespace()),
    ],
)
async def test_uninitialized_turn_skips_maintenance_and_releases_priority(monkeypatch, state, user):
    scheduler = IdleScheduler(grace_seconds=0)
    monkeypatch.setattr(scheduling, "scheduler", scheduler)
    update = AsyncMock()
    monkeypatch.setattr(worker, "request_update", update)
    manager = SimpleNamespace(game_id="session", state=state, user=user)

    @foreground_turn
    async def stream(manager):
        yield "error"

    assert [chunk async for chunk in stream(manager)] == ["error"]
    update.assert_not_awaited()
    assert scheduler.active_turns == 0


async def test_shutdown_cancels_jobs_and_discards_wakeups():
    task = asyncio.create_task(asyncio.Event().wait())
    worker._tasks["shutdown-session"] = task
    worker._wakeups["shutdown-session"] = "owner"
    task.add_done_callback(lambda done: worker._finish("shutdown-session", done))
    await worker.shutdown()
    assert task.cancelled()
    assert not worker._tasks and not worker._wakeups


async def test_worker_claims_once_and_epoch_change_fences_vector_write(journal_world, monkeypatch):
    owner, _ = journal_world
    async with TestSessionLocal() as db:
        await worker.mark_dirty(db, "portrait-session", owner, None)
        await db.commit()
    claim = await worker._claim("portrait-session", owner)
    assert claim is not None
    assert await worker._claim("portrait-session", owner) is None
    async with TestSessionLocal() as db:
        row = await db.get(MemoryIndexState, "portrait-session")
        row.epoch += 1
        row.paused = True
        await db.commit()
    upsert = AsyncMock()
    monkeypatch.setattr(worker.LanceMemoryStore, "upsert", upsert)
    assert not await worker._write_batch(claim, "signature", [], [])
    upsert.assert_not_awaited()


async def test_dirty_marks_preserve_clear_pause_and_retry_is_durable(journal_world):
    owner, _ = journal_world
    async with TestSessionLocal() as db:
        await worker.mark_dirty(db, "portrait-session", owner, None)
        await db.commit()
        row = await db.get(MemoryIndexState, "portrait-session")
        row.paused = True
        row.status = "paused"
        await db.commit()
        await worker.mark_dirty(db, "portrait-session", owner, None)
        await db.commit()
        await db.refresh(row)
        assert row.paused and row.status == "paused" and row.desired_revision == 2
    claim = await worker._claim("portrait-session", owner)
    await worker._failed(claim)
    assert await worker._claim("portrait-session", owner) is None


async def test_dirty_mark_synchronizes_detached_template(journal_world):
    from backend.models.game_session import GameSession

    owner, _ = journal_world
    async with TestSessionLocal() as db:
        session = await db.get(GameSession, "portrait-session")
        await worker.mark_dirty(db, session.id, owner, session.template_id)
        await db.commit()
        row = await db.get(MemoryIndexState, session.id)
        assert row.template_id is not None
        await worker.mark_dirty(db, session.id, owner, None)
        await db.commit()
        await db.refresh(row)
        assert row.template_id is None
        assert row.desired_revision == 2


async def test_embedding_work_is_one_small_batch(monkeypatch):
    monkeypatch.setattr(worker, "scheduler", IdleScheduler(grace_seconds=0))
    user = SimpleNamespace(llm_settings={"memory_rag": {"enabled": True}})
    documents = [
        SimpleNamespace(id=str(i), source_hash=str(i), text=f"Text {i}") for i in range(70)
    ]
    embed = AsyncMock(return_value=[[0.1, 0.2]] * worker.BATCH_SIZE)
    monkeypatch.setattr(worker, "embed_texts", embed)
    monkeypatch.setattr(worker, "_write_batch", AsyncMock(return_value=True))
    claim = worker.Claim("session", "owner", 0, 1, "token", None, False)
    assert await worker._index_batch(claim, user, documents)
    assert len(embed.await_args.args[1]) == worker.BATCH_SIZE


async def test_paused_worker_runs_chronicle_without_embedding(journal_world, monkeypatch):
    owner, _ = journal_world
    user = SimpleNamespace(llm_settings={"memory_rag": {"enabled": True}})
    monkeypatch.setattr(worker, "_load", AsyncMock(return_value=(user, object(), [])))
    index = AsyncMock()
    summarize = AsyncMock(return_value=False)
    monkeypatch.setattr(worker, "_index_batch", index)
    monkeypatch.setattr(worker, "_summarize", summarize)
    monkeypatch.setattr(worker, "_release", AsyncMock())
    claim = worker.Claim("portrait-session", owner, 1, 1, "token", None, True)
    assert not await worker._step(claim)
    index.assert_not_awaited()
    summarize.assert_awaited_once_with(claim, chronicle=True)
