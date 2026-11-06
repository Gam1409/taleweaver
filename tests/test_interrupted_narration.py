"""Delivery failures cannot erase a committed answer or the player's retryable action."""

import asyncio
import json

import pytest
from sqlalchemy import select

from backend.api.routes.adventures.gameplay_logic import GameTurnManager
from backend.engine.turn_replay import drafts
from backend.models.chat import ChatMessage
from backend.models.session_state import SessionState
from backend.models.turn_replay import TurnReplay
from tests.conftest import TestSessionLocal
from tests.test_vn_turn_integration import ACTION, NARRATION, TurnRoles, install_roles, seed_vn


async def test_committed_answer_survives_post_commit_failure(monkeypatch):
    install_roles(monkeypatch, TurnRoles())

    def fail(*_args):
        raise RuntimeError("A post-commit background scheduler failed")

    monkeypatch.setattr("backend.api.routes.adventures.gameplay_logic.schedule_npc_journal", fail)
    async with TestSessionLocal() as db:
        user, _, _, _ = await seed_vn(db)
        host = GameTurnManager(db, "session-1", user)
        chunks = [part async for part in host.process_turn(ACTION)]
        assert any(part.startswith("event: error") for part in chunks)
        replies = list(
            await db.scalars(
                select(ChatMessage).where(
                    ChatMessage.session_id == "session-1", ChatMessage.role == "assistant"
                )
            )
        )
        assert any(reply.content == NARRATION for reply in replies)
        replay = await db.get(TurnReplay, "session-1")
        assert replay.status == "ready"
        assert any(
            reply.id == replay.assistant_id and reply.content == NARRATION for reply in replies
        )
        error = json.loads(
            next(part for part in chunks if part.startswith("event: error")).split("data: ", 1)[1]
        )
        assert error["committed_assistant_id"] == replay.assistant_id
        assert error["retryable"] is False


async def test_disconnect_preserves_visible_draft_outside_canonical_history_and_retry_survives_reload(
    monkeypatch,
):
    install_roles(monkeypatch, TurnRoles())
    waiting = asyncio.Event()

    async def stall(*_args, **_kwargs):
        waiting.set()
        await asyncio.Event().wait()

    monkeypatch.setattr("backend.api.routes.adventures.gameplay_logic.reconcile_items", stall)
    async with TestSessionLocal() as db:
        user, _, _, _ = await seed_vn(db)
        host = GameTurnManager(db, "session-1", user)

        async def consume():
            return [part async for part in host.process_turn(ACTION)]

        task = asyncio.create_task(consume())
        await asyncio.wait_for(waiting.wait(), 10)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    async with TestSessionLocal() as fresh:
        state = await fresh.scalar(
            select(SessionState).where(SessionState.session_id == "session-1")
        )
        pending = await drafts.pending(fresh, state)
        assert pending["action"] == ACTION and pending["draft"] == NARRATION
        assert await drafts.pending(fresh, state, busy=True) is None
        replies = list(
            await fresh.scalars(
                select(ChatMessage).where(
                    ChatMessage.session_id == "session-1", ChatMessage.role == "assistant"
                )
            )
        )
        assert all(reply.content != NARRATION for reply in replies)


async def test_retry_uses_original_saved_input_and_clears_draft_only_after_success(monkeypatch):
    roles = TurnRoles()
    install_roles(monkeypatch, roles)
    original = GameTurnManager._run_llm_cycle

    async def interrupted(host, *_args, **_kwargs):
        from backend.engine.turn_replay.transactions import release_for_model

        await release_for_model(host)
        drafts.observe(host, "Unfinished answer")
        yield 'event: error\ndata: {"detail":"Interrupted"}\n\n'

    monkeypatch.setattr(GameTurnManager, "_run_llm_cycle", interrupted)
    async with TestSessionLocal() as db:
        user, _, _, _ = await seed_vn(db)
        host = GameTurnManager(db, "session-1", user)
        _ = [part async for part in host.process_turn(ACTION)]
        state = await db.scalar(select(SessionState).where(SessionState.session_id == "session-1"))
        assert (await drafts.pending(db, state))["draft"] == "Unfinished answer"
        monkeypatch.setattr(GameTurnManager, "_run_llm_cycle", original)
        host = GameTurnManager(db, "session-1", user)
        chunks = [part async for part in host.process_turn(ACTION)]
        assert any(part.startswith("event: final") for part in chunks)
        history = list(
            await db.scalars(select(ChatMessage).where(ChatMessage.session_id == "session-1"))
        )
        assert sum(message.role == "user" and message.content == ACTION for message in history) == 1
        assert await drafts.pending(db, host.state) is None
        assert drafts.KEY not in host.state.entity_states
