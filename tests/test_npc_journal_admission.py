"""Admission fences defer journal work without consuming retries or losing prose."""

import asyncio
import time
from unittest.mock import AsyncMock

import pytest

from backend.core.inference import transport
from backend.core.inference.registry import InferenceQueueError, InferenceUncertainError
from backend.engine.npc_journal import queue, worker
from backend.engine.npc_journal.schema import JournalExtraction
from backend.models.chat import ChatMessage
from tests.conftest import TestSessionLocal
from tests.test_inference_integration import reservations
from tests.test_inference_reservations import KEY, router
from tests.test_npc_journal import INTRO, journal_world, portrait_world, save_message

__all__ = ["journal_world", "portrait_world", "reservations"]


@pytest.mark.parametrize(
    "error",
    [InferenceUncertainError("Unconfirmed previous request"), InferenceQueueError("Queue busy")],
)
async def test_queue_fence_defers_without_spending_an_extraction_attempt(
    journal_world, monkeypatch, error, caplog
):
    owner, portraits = journal_world
    message_id = await save_message()
    extract = AsyncMock(side_effect=error)
    monkeypatch.setattr(worker, "extract", extract)
    assert not await worker.process_message(message_id, owner)
    async with TestSessionLocal() as db:
        message = await db.get(ChatMessage, message_id)
        assert message.content == INTRO
        task = message.npc_journal
        assert task["status"] == "pending" and task["attempts"] == 0
        assert task["retry_after"] > time.time()
        assert not queue.eligible(task, time.time())
        assert await queue.next_message(db, message.session_id) is None
        assert await queue.next_retry_at(db, message.session_id) == task["retry_after"]
    portraits.assert_not_called()
    assert extract.await_count == 1
    assert not any(record.levelname == "ERROR" for record in caplog.records)


@pytest.mark.parametrize("serialized", [True, False])
async def test_activity_before_transport_returns_journal_to_pending_then_runs_once(
    journal_world, reservations, monkeypatch, serialized
):
    owner, _ = journal_world
    message_id = await save_message()
    scheduler = worker.scheduler
    monkeypatch.setattr(worker.settings, "NPC_JOURNAL_PLAYER_IDLE_SECONDS", 90)
    monkeypatch.setattr(worker.settings, "INFERENCE_SERIALIZATION_ENABLED", serialized)
    scheduler.last_player_activity -= 100
    preparing, proceed = asyncio.Event(), asyncio.Event()
    sent = []
    held = reservations.enqueue(KEY)
    assert reservations.try_acquire(held)

    @transport.guarded_async
    async def request(router, args):
        sent.append(True)
        return JournalExtraction()

    async def extract(*args):
        preparing.set()
        if not serialized:
            await proceed.wait()
        return await request(router(), {})

    monkeypatch.setattr(worker, "extract", extract)
    task = asyncio.create_task(worker.process_message(message_id, owner))
    await asyncio.wait_for(preparing.wait(), 2)
    if serialized:
        assert len(reservations.waiters) == 1
    scheduler.player_returned()
    proceed.set()
    assert not await asyncio.wait_for(task, 2)
    assert not sent and not reservations.waiters
    reservations.finish(held, certain=True)
    async with TestSessionLocal() as db:
        source = await db.get(ChatMessage, message_id)
        assert source.content == INTRO
        assert source.npc_journal["status"] == "pending" and source.npc_journal["attempts"] == 0
    scheduler.last_player_activity -= 100
    assert await worker.process_message(message_id, owner)
    assert sent == [True]
    assert not await worker.process_message(message_id, owner)


async def test_player_turn_after_dispatch_preserves_the_single_extraction(
    journal_world, monkeypatch
):
    owner, _ = journal_world
    message_id = await save_message()
    sent, finish = asyncio.Event(), asyncio.Event()

    async def answer(*args):
        sent.set()
        await finish.wait()
        return JournalExtraction()

    extract = AsyncMock(side_effect=answer)
    monkeypatch.setattr(worker, "extract", extract)
    task = asyncio.create_task(worker.process_message(message_id, owner))
    await asyncio.wait_for(sent.wait(), 2)
    async with worker.scheduler.foreground():
        assert not task.done()
    finish.set()
    assert await asyncio.wait_for(task, 2)
    assert not await worker.process_message(message_id, owner)
    extract.assert_awaited_once()
    async with TestSessionLocal() as db:
        source = await db.get(ChatMessage, message_id)
        assert source.npc_journal["status"] == "done" and source.npc_journal["attempts"] == 1
