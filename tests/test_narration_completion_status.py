"""Committed partial narratives are visible as incomplete without repeating actions."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import select

from backend.api.routes.adventures.gameplay_logic import GameTurnManager
from backend.engine.rule_engine import GameEvent
from backend.models.chat import ChatMessage
from tests.conftest import TestSessionLocal
from tests.llm_fakes import RoleLLMFactory
from tests.test_game_loop import _seed_game_context


@pytest.mark.parametrize("ending", ["length", "error", "stop"])
async def test_partial_narration_commits_once_and_reports_warning(monkeypatch, ending):
    llm = MagicMock()
    llm.aexecute_complex_task = AsyncMock(return_value=GameEvent(narrative_description="A reply."))

    async def stream():
        yield SimpleNamespace(
            choices=[
                SimpleNamespace(
                    delta=SimpleNamespace(content="<sigh> Give me "), finish_reason=None
                )
            ]
        )
        if ending == "error":
            raise ConnectionResetError("provider disconnected")
        yield SimpleNamespace(
            choices=[SimpleNamespace(delta=SimpleNamespace(content=""), finish_reason=ending)]
        )

    llm.stream_simple_task = AsyncMock(side_effect=lambda *a, **kw: stream())
    monkeypatch.setattr(
        "backend.api.routes.adventures.gameplay_logic.GameMasterLLM",
        RoleLLMFactory(lambda *a, **kw: llm),
    )
    async with TestSessionLocal() as db:
        user, _, _, _ = await _seed_game_context(db)
        manager = GameTurnManager(db, "session-1", user)
        events = [event async for event in manager.process_turn("I ask her a question")]
        final = next(
            json.loads(event.split("data: ", 1)[1])
            for event in events
            if event.startswith("event: final")
        )
        assert final["narration_incomplete"] == (ending != "stop")
        assert bool(final["narration_warning"]) == (ending != "stop")
        rows = (
            await db.scalars(
                select(ChatMessage).where(
                    ChatMessage.session_id == "session-1", ChatMessage.role == "assistant"
                )
            )
        ).all()
        assert len(rows) == 1 and rows[0].content == "<sigh> Give me "
    llm.stream_simple_task.assert_awaited_once()
