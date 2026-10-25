"""Failed extraction must not strand a journal or duplicate model work."""

import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock

import pytest_asyncio
from sqlalchemy import select

from backend.engine.npc_journal import queue, worker
from backend.engine.npc_journal.messages import restore_messages
from backend.engine.npc_journal.records import journal_of
from backend.engine.npc_journal.schema import CharacterObservation, JournalExtraction
from backend.models.chat import ChatMessage
from backend.models.world_entity import WorldEntity
from tests.conftest import TestSessionLocal
from tests.test_npc_journal import (
    introduction,
    journal_world,
    observation,
    portrait_world,
    save_message,
)

__all__ = ["journal_world", "portrait_world"]


@pytest_asyncio.fixture(autouse=True)
async def clean_workers(monkeypatch):
    monkeypatch.setattr(worker, "resume_pending", AsyncMock())
    worker._cooldowns.clear()
    worker._wakeups.clear()
    yield
    await worker.shutdown()


async def task_for(message_id):
    async with TestSessionLocal() as db:
        return (await db.get(ChatMessage, message_id)).npc_journal


async def set_task(message_id, task):
    async with TestSessionLocal() as db:
        (await db.get(ChatMessage, message_id)).npc_journal = task
        await db.commit()


async def test_failed_introduction_does_not_strand_later_facts_and_recovery_replays_them(
    journal_world, monkeypatch
):
    owner, _ = journal_world
    now = datetime.now()
    first = await save_message(created_at=now)
    later = await save_message("Мира сказала: «Я кузнец».", created_at=now + timedelta(seconds=1))
    first_fails = True
    calls = []

    async def extract(user, session, message_id, payload):
        calls.append(message_id)
        if message_id == first and first_fails:
            raise RuntimeError("model offline")
        characters = (
            [introduction(observations=[observation()])]
            if message_id == first
            else [
                CharacterObservation(
                    name="Мира",
                    observations=[
                        observation("background", "Кузнец", "Я кузнец", topic="occupation")
                    ],
                )
            ]
        )
        return JournalExtraction(characters=characters)

    monkeypatch.setattr(worker, "extract", extract)
    await worker._run("portrait-session", owner)
    assert calls == [first, later]
    assert (await task_for(first))["status"] == "failed"
    assert (await task_for(later))["status"] == "done"
    assert (await task_for(later))["gaps"] == [first]
    # A retry after the cooldown learns the introduction, then revisits dependent facts.
    first_fails = False
    failed = await task_for(first)
    await set_task(first, {**failed, "retry_after": 0})
    await worker._run("portrait-session", owner)
    assert calls == [first, later, first, later]
    async with TestSessionLocal() as db:
        npc = await db.scalar(select(WorldEntity).where(WorldEntity.name == "Мира"))
        entries = journal_of(npc)["entries"]
    assert [entry["message_id"] for entry in entries] == [first, later]
    assert [entry["text"] for entry in entries] == ["Синий плащ", "Кузнец"]


async def test_retries_have_cooldown_and_stop_after_three_attempts(journal_world, monkeypatch):
    owner, _ = journal_world
    message_id = await save_message()
    extract = AsyncMock(side_effect=RuntimeError("offline"))
    monkeypatch.setattr(worker, "extract", extract)
    for attempt in range(1, 4):
        await worker._run("portrait-session", owner)
        assert extract.await_count == attempt
        await worker._run("portrait-session", owner)
        assert extract.await_count == attempt
        task = await task_for(message_id)
        assert task["status"] == "failed" and task["attempts"] == attempt
        await set_task(message_id, {**task, "retry_after": 0})
    await worker._run("portrait-session", owner)
    assert extract.await_count == 3


async def test_outage_does_not_burn_the_entire_backlog(journal_world, monkeypatch):
    owner, _ = journal_world
    for _ in range(8):
        await save_message()
    extract = AsyncMock(side_effect=RuntimeError("offline"))
    monkeypatch.setattr(worker, "extract", extract)
    await worker._run("portrait-session", owner)
    await worker._run("portrait-session", owner)
    assert extract.await_count == 2


async def test_concurrent_calls_claim_message_once_and_ignore_stale_completion(
    journal_world, monkeypatch
):
    owner, portraits = journal_world
    message_id = await save_message()
    started, release = asyncio.Event(), asyncio.Event()

    async def extract(*args):
        started.set()
        await release.wait()
        return JournalExtraction(characters=[introduction()])

    mock = AsyncMock(side_effect=extract)
    monkeypatch.setattr(worker, "extract", mock)
    first = asyncio.create_task(worker.process_message(message_id, owner))
    await started.wait()
    assert not await worker.process_message(message_id, owner)
    # An explicit reset while extraction is in flight invalidates its claim.
    await set_task(message_id, {"status": "pending", "attempts": 0})
    release.set()
    assert not await first
    assert (await task_for(message_id))["status"] == "pending"
    assert mock.await_count == 1
    portraits.assert_not_called()


async def test_expired_last_attempt_becomes_visible_failure_and_queue_continues(
    journal_world, monkeypatch
):
    owner, _ = journal_world
    first = await save_message()
    later = await save_message()
    await set_task(first, {"status": "running", "attempts": 3, "lease_until": 0})
    monkeypatch.setattr(worker, "extract", AsyncMock(return_value=JournalExtraction(characters=[])))
    await worker._run("portrait-session", owner)
    assert (await task_for(first))["status"] == "failed"
    assert (await task_for(later))["status"] == "done"


async def test_schedule_deduplicates_and_preserves_a_wakeup_during_worker_exit(monkeypatch):
    entered, release, resumed = asyncio.Event(), asyncio.Event(), asyncio.Event()
    calls = []

    async def run(*args):
        calls.append(args)
        entered.set()
        if len(calls) == 1:
            await release.wait()
        else:
            resumed.set()

    monkeypatch.setattr(worker, "_run", run)
    worker.schedule("s", "u")
    await entered.wait()
    for _ in range(5):
        worker.schedule("s", "u")
    assert len(worker._tasks) == 1
    release.set()
    await asyncio.wait_for(resumed.wait(), 1)
    await asyncio.sleep(0)
    assert len(calls) == 2


async def test_shutdown_releases_claim_without_restarting_queued_work(journal_world, monkeypatch):
    owner, _ = journal_world
    message_id = await save_message()
    started = asyncio.Event()

    async def extract(*args):
        started.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(worker, "extract", extract)
    worker.schedule("portrait-session", owner)
    await started.wait()
    worker.schedule("portrait-session", owner)
    await worker.shutdown()
    assert not worker._tasks and not worker._wakeups
    task = await task_for(message_id)
    assert task["status"] == "failed" and task["attempts"] == 1


async def test_restore_remaps_gap_ids_and_discards_old_running_claim(journal_world):
    async with TestSessionLocal() as db:
        ids = restore_messages(
            db,
            "portrait-session",
            [
                {
                    "id": "intro",
                    "role": "assistant",
                    "content": "intro",
                    "npc_journal": {"status": "failed"},
                },
                {
                    "id": "later",
                    "role": "assistant",
                    "content": "later",
                    "npc_journal": {
                        "status": "running",
                        "attempts": 2,
                        "token": "old",
                        "lease_until": 9999999999,
                        "gaps": ["intro"],
                    },
                },
            ],
        )
        await db.commit()
    task = await task_for(ids["later"])
    assert task["gaps"] == [ids["intro"]]
    assert task["status"] == "pending" and "token" not in task


async def test_session_claim_prevents_parallel_extraction_of_later_messages(journal_world):
    first, later = await save_message(), await save_message()
    async with TestSessionLocal() as db:
        claimed = await queue.claim(db, await db.get(ChatMessage, first))
        assert claimed is not None
    async with TestSessionLocal() as db:
        assert await queue.next_message(db, "portrait-session") is None
        assert await queue.claim(db, await db.get(ChatMessage, later)) is None
    await set_task(first, {**claimed, "lease_until": 0})
    async with TestSessionLocal() as db:
        assert await queue.next_message(db, "portrait-session") is not None


async def test_context_failure_is_durable_and_does_not_leave_running_claim(
    journal_world, monkeypatch
):
    owner, _ = journal_world
    message_id = await save_message()
    monkeypatch.setattr(worker, "extraction_context", AsyncMock(side_effect=ValueError("context")))
    assert not await worker.process_message(message_id, owner)
    assert (await task_for(message_id))["status"] == "failed"


async def test_stale_done_callback_cannot_remove_newer_session_worker(monkeypatch):
    old = asyncio.create_task(asyncio.sleep(0))
    newer = asyncio.create_task(asyncio.sleep(0))
    worker._tasks["s"] = newer
    await old
    worker._finish("s", old)
    assert worker._tasks["s"] is newer
    await newer
    worker._finish("s", newer)
