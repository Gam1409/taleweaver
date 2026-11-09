"""Protect the entire agent write cycle and complete saved narration."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from litellm import ModelResponse
from sqlalchemy import select

from backend.api.routes.adventures import regeneration
from backend.core.llm_router import GameMasterLLM
from backend.engine.gameplay.agent_logic import AgentDecision, AgentService
from backend.engine.visual_novel.concurrency import session_write_lease
from backend.models.chat import ChatMessage
from backend.models.session_state import SessionState
from backend.models.user import User
from tests.conftest import TestSessionLocal
from tests.test_session_portraits import portrait_world

__all__ = ["portrait_world"]


@pytest.mark.parametrize("finish_reason", ["length", "max_tokens", "content_filter", "tool_calls"])
async def test_truncated_rewrite_must_not_replace_a_complete_saved_reply(
    auth_client, portrait_world, monkeypatch, finish_reason
):
    async with TestSessionLocal() as db:
        original = ChatMessage(
            session_id="portrait-session", role="assistant", content="The gate remains locked."
        )
        db.add(original)
        await db.commit()
        identifier = original.id
        before = (await db.execute(select(ChatMessage.__table__))).mappings().all()
        state_before = (await db.execute(select(SessionState.__table__))).mappings().all()
    user = User(
        username="offline-audit",
        llm_settings={"complex_model_provider": "ollama", "complex_model": "local-test"},
        encrypted_api_keys={},
    )
    router = GameMasterLLM.for_role(user, "complex")
    router.max_tokens = 16
    transport = AsyncMock(
        return_value=ModelResponse(
            choices=[
                {
                    "message": {"role": "assistant", "content": "The gate begins to"},
                    "finish_reason": finish_reason,
                }
            ],
            usage={"prompt_tokens": 100, "completion_tokens": 16, "total_tokens": 116},
        )
    )
    monkeypatch.setattr(router, "_acompletion_with_openrouter_fallback", transport)
    monkeypatch.setattr(regeneration, "GameMasterLLM", SimpleNamespace(for_role=lambda *_: router))
    monkeypatch.setattr(regeneration, "schedule", lambda *_: None)
    monkeypatch.setattr(regeneration, "queue_refresh", lambda *_: None)
    result = await auth_client.post(
        "/api/adventures/portrait-session/chat/regenerate", json={"message_id": identifier}
    )
    async with TestSessionLocal() as db:
        stored = (await db.get(ChatMessage, identifier)).content
        assert (await db.execute(select(ChatMessage.__table__))).mappings().all() == before
        assert (await db.execute(select(SessionState.__table__))).mappings().all() == state_before
    assert result.status_code in {502, 504}, (result.status_code, stored)
    assert stored == "The gate remains locked."
    transport.assert_awaited_once()


async def test_agent_settings_must_respect_an_active_turn_lease(auth_client, portrait_world):
    with session_write_lease("portrait-session"):
        result = await auth_client.patch(
            "/api/adventures/portrait-session/agent/settings", json={"active": True}
        )
    assert result.status_code == 409, result.text


async def test_agent_turn_must_not_decide_or_write_while_a_session_is_busy(
    auth_client, portrait_world, monkeypatch
):
    async with TestSessionLocal() as db:
        state = await db.scalar(
            select(SessionState).where(SessionState.session_id == "portrait-session")
        )
        AgentService.set_agent_active(state, True)
        await db.commit()
    decide = AsyncMock(
        return_value=AgentDecision(
            thoughts="Offline audit",
            action="wait",
            is_stuck_or_bug=True,
            issue_description="No action available",
        )
    )
    monkeypatch.setattr(AgentService, "get_decision", decide)
    monkeypatch.setattr(AgentService, "log_issue", lambda *_: None)
    with session_write_lease("portrait-session"):
        result = await auth_client.post("/api/adventures/portrait-session/agent/turn")
    async with TestSessionLocal() as db:
        state = await db.scalar(
            select(SessionState).where(SessionState.session_id == "portrait-session")
        )
        failures = AgentService.get_agent_state(state)["failure_count"]
    assert result.status_code == 409, (result.status_code, decide.await_count, failures)
    decide.assert_not_awaited()
