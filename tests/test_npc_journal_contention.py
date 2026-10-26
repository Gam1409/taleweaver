"""SQLite retries preserve extraction results and revalidate their source."""

import asyncio
import sqlite3
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from backend.engine.memory_rag import persistence
from backend.engine.npc_journal import worker
from backend.engine.npc_journal.schema import JournalExtraction
from backend.models.chat import ChatMessage
from backend.models.world_entity import WorldEntity
from tests.conftest import TestSessionLocal
from tests.test_npc_journal import introduction, journal_world, portrait_world, save_message

__all__ = ["journal_world", "portrait_world"]


def locked():
    return OperationalError(
        "UPDATE chat_messages", {}, sqlite3.OperationalError("database is locked")
    )


async def test_save_retries_rolled_back_writes_without_repeating_model(journal_world, monkeypatch):
    owner, portraits = journal_world
    message_id = await save_message()
    model = AsyncMock(return_value=JournalExtraction(characters=[introduction()]))
    monkeypatch.setattr(worker, "extract", model)
    monkeypatch.setattr(persistence, "RETRY_DELAYS", (0,))
    original = worker.apply_extraction
    sessions = []

    async def apply(db, *args):
        sessions.append(db)
        result = await original(db, *args)
        await db.flush()
        if len(sessions) == 1:
            raise locked()
        return result

    monkeypatch.setattr(worker, "apply_extraction", apply)
    assert await worker.process_message(message_id, owner)
    assert model.await_count == 1
    assert len(sessions) == 2 and sessions[0] is not sessions[1]
    portraits.assert_called_once()
    async with TestSessionLocal() as db:
        assert (await db.get(ChatMessage, message_id)).npc_journal["status"] == "done"
        assert (
            len((await db.scalars(select(WorldEntity).where(WorldEntity.name == "Мира"))).all())
            == 1
        )


@pytest.mark.parametrize("change", ["content", "claim", "delete"])
async def test_save_retry_rechecks_source_and_claim(journal_world, monkeypatch, change):
    owner, portraits = journal_world
    message_id = await save_message()
    monkeypatch.setattr(
        worker, "extract", AsyncMock(return_value=JournalExtraction(characters=[introduction()]))
    )
    monkeypatch.setattr(persistence, "RETRY_DELAYS", (0,))
    original = worker.queue.fence
    calls = 0

    async def fence(db, message, token):
        nonlocal calls
        calls += 1
        if calls != 1:
            return await original(db, message, token)
        # Simulate a competing committed edit before the failed transaction retries.
        await db.rollback()
        async with TestSessionLocal() as other:
            current = await other.get(ChatMessage, message_id)
            if change == "content":
                current.content = "Edited narration"
            elif change == "claim":
                current.npc_journal = {"status": "pending", "attempts": 0}
            else:
                await other.delete(current)
            await other.commit()
        raise locked()

    monkeypatch.setattr(worker.queue, "fence", fence)
    assert not await worker.process_message(message_id, owner)
    portraits.assert_not_called()
    async with TestSessionLocal() as db:
        assert await db.scalar(select(WorldEntity).where(WorldEntity.name == "Мира")) is None


@pytest.mark.parametrize("error", [ValueError("bad data"), asyncio.CancelledError()])
async def test_non_contention_and_cancellation_are_not_retried(error):
    operation = AsyncMock(side_effect=error)
    with pytest.raises(type(error)):
        await persistence.retry_transaction(operation)()
    assert operation.await_count == 1


async def test_busy_retry_is_bounded(monkeypatch):
    monkeypatch.setattr(persistence, "RETRY_DELAYS", (0, 0))
    operation = AsyncMock(side_effect=locked())
    with pytest.raises(OperationalError):
        await persistence.retry_transaction(operation)()
    assert operation.await_count == 3
