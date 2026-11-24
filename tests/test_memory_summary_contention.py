"""Retry generated summaries without repeating LLM work or accepting stale sources."""

import json
import sqlite3
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from backend.core.llm_structured_execution import OutputLimitError
from backend.engine.memory_rag import chronicle, persistence, summaries
from backend.models.chat import ChatMessage
from backend.models.memory_rag import MemoryIndexState, MemorySummary
from backend.models.session_state import SessionState
from tests.conftest import TestSessionLocal
from tests.test_llm_structured_single_attempt import completion, mock_http, router
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


async def _session_state(db):
    return await db.scalar(
        select(SessionState).where(SessionState.session_id == "portrait-session")
    )


async def test_truncated_chronicle_keeps_previous_summary_and_cursor(journal_world, monkeypatch):
    owner, _ = journal_world
    await seed(owner)
    request = AsyncMock(side_effect=OutputLimitError("Output limit"))
    model = SimpleNamespace(model="fake", aexecute_simple_task=request)
    monkeypatch.setattr(chronicle.GameMasterLLM, "for_role", lambda *_: model)
    monkeypatch.setattr(chronicle.scheduler, "can_start_background", lambda: True)

    with pytest.raises(OutputLimitError):
        await run("chronicle", owner)

    assert request.await_args.kwargs["require_complete_output"] is True
    assert request.await_count == 2
    async with TestSessionLocal() as db:
        state = await _session_state(db)
        assert state.compressed_history == {"summary": "Old history"}


async def test_chronicle_retries_wire_truncation_with_smaller_exact_source_batch(
    journal_world, monkeypatch
):
    owner, _ = journal_world
    await seed(owner)
    prior = "Earlier account. " * 700
    async with TestSessionLocal() as db:
        state = await _session_state(db)
        state.compressed_history = {"summary": prior}
        for message in await db.scalars(select(ChatMessage)):
            message.content += " A recorded event." * 60
        await db.commit()

    llm = router(monkeypatch)
    llm.model = "local-model"
    responses = iter([("An unfinished", "length"), ("A complete chronicle.", "stop")])
    prompts = []

    async def respond(request):
        prompts.append(json.loads(request.content)["messages"])
        async with TestSessionLocal() as db:
            state = await _session_state(db)
            assert state.compressed_history == {"summary": prior}
        return httpx.Response(200, request=request, json=completion(*next(responses)))

    mock_http(monkeypatch, respond)
    monkeypatch.setattr(chronicle.GameMasterLLM, "for_role", lambda *_: llm)
    monkeypatch.setattr(chronicle.scheduler, "can_start_background", lambda: True)

    assert await run("chronicle", owner)
    first, second = prompts
    assert sum(len(msg["content"]) for msg in first) <= chronicle.MAX_PROMPT_CHARS
    first_events, second_events = (
        prompt[-1]["content"].split("New past sources:\n", 1)[1] for prompt in prompts
    )
    assert first_events.startswith(second_events)
    assert len(second_events) <= len(first_events) // 2
    assert prior in second[-1]["content"]
    async with TestSessionLocal() as db:
        state = await _session_state(db)
        assert state.compressed_history["summary"] == "A complete chronicle."
        follow_up = await chronicle._batch(db, state)
        assert follow_up is not None
        assert state.compressed_history["pending_message_id"]
        pending = await db.get(ChatMessage, state.compressed_history["pending_message_id"])
        offset = state.compressed_history["pending_offset"]
        assert second_events.endswith(pending.content[:offset])
        assert pending.content[offset:] in follow_up["events"]


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
