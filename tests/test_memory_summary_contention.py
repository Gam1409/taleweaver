"""Retry generated summaries without repeating LLM work or accepting stale sources."""

import sqlite3
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from backend.engine.memory_rag import chronicle, persistence, summaries
from backend.models.chat import ChatMessage
from backend.models.memory_rag import MemoryIndexState, MemorySummary
from backend.models.session_state import SessionState
from tests.conftest import TestSessionLocal
from tests.test_npc_journal import journal_world, portrait_world

__all__ = ["journal_world", "portrait_world"]


def busy():
    return OperationalError(
        "UPDATE memory_index_states", {}, sqlite3.OperationalError("database is locked")
    )


async def seed(owner):
    async with TestSessionLocal() as db:
        state = await db.scalar(
            select(SessionState).where(SessionState.session_id == "portrait-session")
        )
        state.max_memory_turns = 1
        state.enable_history_compression = True
        state.compressed_history = {"summary": "Old history"}
        for index in range(6):
            db.add(
                ChatMessage(session_id=state.session_id, role="user", content=f"Question {index}")
            )
            db.add(
                ChatMessage(
                    session_id=state.session_id, role="assistant", content=f"Answer {index}"
                )
            )
            await db.flush()
        db.add(
            MemoryIndexState(
                session_id=state.session_id, user_id=owner, epoch=0, lease_token="lease"
            )
        )
        await db.commit()


async def run(kind, owner):
    operation = (
        summaries.summarize_one_group if kind == "summary" else chronicle.compress_history_one_group
    )
    async with TestSessionLocal() as db:
        state = await db.scalar(
            select(SessionState).where(SessionState.session_id == "portrait-session")
        )
        return await operation(db, SimpleNamespace(id=owner), state, epoch=0, lease_token="lease")


@pytest.mark.parametrize("kind", ["summary", "chronicle"])
@pytest.mark.parametrize("change", [None, "source", "lease"])
async def test_summary_save_retries_and_revalidates(journal_world, monkeypatch, kind, change):
    owner, _ = journal_world
    await seed(owner)
    model = SimpleNamespace(
        model="fake", aexecute_simple_task=AsyncMock(return_value="New history")
    )
    monkeypatch.setattr(summaries.GameMasterLLM, "for_role", lambda *_: model)
    monkeypatch.setattr(summaries.scheduler, "can_start_background", lambda: True)
    monkeypatch.setattr(persistence, "RETRY_DELAYS", (0,))
    module = summaries if kind == "summary" else chronicle
    original = module.lock_fence
    attempts = []

    async def lock(db, *args, **kwargs):
        attempts.append(db)
        matched = await original(db, *args, **kwargs)
        if len(attempts) != 1:
            return matched
        # The failed transaction must be discarded, including its revision increment.
        await db.rollback()
        if change:
            async with TestSessionLocal() as other:
                if change == "lease":
                    control = await other.get(MemoryIndexState, "portrait-session")
                    control.epoch += 1
                    control.lease_token = None
                else:
                    message = await other.scalar(
                        select(ChatMessage)
                        .order_by(ChatMessage.created_at, ChatMessage.id)
                        .limit(1)
                    )
                    message.content = "Corrected source"
                await other.commit()
        raise busy()

    monkeypatch.setattr(module, "lock_fence", lock)
    assert await run(kind, owner)
    assert model.aexecute_simple_task.await_count == 1
    assert len(attempts) == 2 and attempts[0] is not attempts[1]
    async with TestSessionLocal() as db:
        control = await db.get(MemoryIndexState, "portrait-session")
        assert control.desired_revision == (2 if change is None else 1)
        if kind == "summary":
            rows = list(await db.scalars(select(MemorySummary)))
            assert len(rows) == (1 if change is None else 0)
        else:
            state = await db.scalar(
                select(SessionState).where(SessionState.session_id == "portrait-session")
            )
            assert state.compressed_history["summary"] == (
                "New history" if change is None else "Old history"
            )
