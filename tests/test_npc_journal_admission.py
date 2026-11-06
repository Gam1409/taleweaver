"""Admission fences defer journal work without consuming retries or losing prose."""

import time
from unittest.mock import AsyncMock

import pytest

from backend.core.inference.registry import InferenceQueueError, InferenceUncertainError
from backend.engine.npc_journal import queue, worker
from backend.models.chat import ChatMessage
from tests.conftest import TestSessionLocal
from tests.test_npc_journal import INTRO, journal_world, portrait_world, save_message

__all__ = ["journal_world", "portrait_world"]


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
