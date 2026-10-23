"""Manual idea refresh must be observable, isolated from turns, and safe on failure."""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from sqlalchemy import func, select

from backend.api.routes.adventures.turn_suggestions import (
    PROMPT_SUGGESTIONS_STATE_KEY,
    TurnSuggestionsManager,
)
from backend.models.chat import ChatMessage
from backend.models.game_session import GameSession
from backend.models.session_state import SessionState
from backend.models.user import User
from tests.conftest import TestSessionLocal
from tests.llm_fakes import RoleLLMFactory
from tests.test_session_portraits import portrait_world

__all__ = ["portrait_world"]

OLD = ["Осмотреть зал", "Поговорить с Линой", "Проверить рюкзак"]
NEW = ["Осмотреть меч", "Прислушаться к звукам", "Спросить Лину о башне"]


async def state_for(db):
    return (
        await db.execute(select(SessionState).where(SessionState.session_id == "portrait-session"))
    ).scalar_one()


@pytest_asyncio.fixture
async def suggestion_model(portrait_world, monkeypatch):
    async with TestSessionLocal() as db:
        state = await state_for(db)
        state.exit_states = {PROMPT_SUGGESTIONS_STATE_KEY: OLD, "door": {"locked": True}}
        session = await db.get(GameSession, state.session_id)
        session.content_language = "Russian"
        user = await db.get(User, session.user_id)
        user.llm_settings = {
            "small_model_provider": "ollama",
            "small_model": "utility-qwen",
            "complex_model_provider": "ollama",
            "complex_model": "narration-artemis",
        }
        await db.commit()
    llm = MagicMock()
    llm.aexecute_simple_task = AsyncMock(return_value=json.dumps(NEW, ensure_ascii=False))
    factory = MagicMock(return_value=llm)
    monkeypatch.setattr(
        "backend.api.routes.adventures.turn_suggestions.GameMasterLLM", RoleLLMFactory(factory)
    )
    return llm, factory


@pytest.mark.parametrize("endpoint", ["suggestions", "shuffle"])
async def test_refresh_updates_only_ideas_with_small_model_and_saved_language(
    auth_client, suggestion_model, endpoint
):
    response = await auth_client.post(f"/api/adventures/portrait-session/{endpoint}")

    assert response.status_code == 200, response.text
    assert response.json()["suggestions"] == NEW
    llm, factory = suggestion_model
    assert factory.call_args.kwargs["model_category"] == "small"
    args = llm.aexecute_simple_task.call_args.args
    assert args[2] == "utility-qwen"
    assert "Russian" in args[0]
    assert "Previous ideas" in args[1] and OLD[0] in args[1]
    async with TestSessionLocal() as db:
        state = await state_for(db)
        assert state.exit_states[PROMPT_SUGGESTIONS_STATE_KEY] == NEW
        assert state.exit_states["door"] == {"locked": True}
        assert state.current_scene_id == "TOWER" and state.in_game_time == 480
        assert await db.scalar(select(func.count()).select_from(ChatMessage)) == 0
    saved = await auth_client.get("/api/adventures/portrait-session/suggestions")
    assert saved.json()["suggestions"] == NEW
    assert llm.aexecute_simple_task.await_count == 1


@pytest.mark.parametrize("output", ["invalid JSON", "[]", '["Only one"]', '{"ideas": []}'])
async def test_invalid_model_output_is_an_error_and_keeps_existing_ideas(
    auth_client, suggestion_model, output
):
    suggestion_model[0].aexecute_simple_task.return_value = output
    response = await auth_client.post("/api/adventures/portrait-session/suggestions")
    assert response.status_code == 502
    async with TestSessionLocal() as db:
        assert (await state_for(db)).exit_states[PROMPT_SUGGESTIONS_STATE_KEY] == OLD


async def test_provider_failure_does_not_leak_details_or_silently_replace_ideas(
    auth_client, suggestion_model
):
    suggestion_model[0].aexecute_simple_task.side_effect = RuntimeError("private provider detail")
    response = await auth_client.post("/api/adventures/portrait-session/suggestions")
    assert response.status_code == 502
    assert "private provider" not in response.text
    async with TestSessionLocal() as db:
        assert (await state_for(db)).exit_states[PROMPT_SUGGESTIONS_STATE_KEY] == OLD


async def test_timeout_cancels_generation_and_preserves_ideas(
    auth_client, suggestion_model, monkeypatch
):
    cancelled = asyncio.Event()

    async def slow_model(*args, **kwargs):
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    monkeypatch.setattr(
        "backend.api.routes.adventures.suggestions.SUGGESTIONS_TIMEOUT_SECONDS", 0.02
    )
    suggestion_model[0].aexecute_simple_task.side_effect = slow_model
    response = await auth_client.post("/api/adventures/portrait-session/suggestions")
    assert response.status_code == 504
    assert cancelled.is_set()
    async with TestSessionLocal() as db:
        assert (await state_for(db)).exit_states[PROMPT_SUGGESTIONS_STATE_KEY] == OLD


@pytest.mark.parametrize("change", ["scene", "language", "exit"])
async def test_refresh_does_not_overwrite_concurrent_state(auth_client, suggestion_model, change):
    async def model_with_concurrent_change(*args, **kwargs):
        async with TestSessionLocal() as db:
            state = await state_for(db)
            if change == "scene":
                state.current_scene_id = "YARD"
            if change == "language":
                session = await db.get(GameSession, state.session_id)
                session.content_language = "Japanese"
            state.exit_states = {**state.exit_states, "door": {"locked": False}}
            await db.commit()
        return json.dumps(NEW)

    suggestion_model[0].aexecute_simple_task.side_effect = model_with_concurrent_change
    response = await auth_client.post("/api/adventures/portrait-session/suggestions")
    assert response.status_code == (200 if change == "exit" else 409), response.text
    async with TestSessionLocal() as db:
        state = await state_for(db)
        assert state.exit_states["door"] == {"locked": False}
        assert state.exit_states[PROMPT_SUGGESTIONS_STATE_KEY] == (NEW if change == "exit" else OLD)


@pytest.mark.parametrize("session_id", ["other-session", "missing-session"])
@pytest.mark.parametrize("method", ["get", "post"])
async def test_refresh_hides_foreign_sessions(auth_client, suggestion_model, session_id, method):
    response = await getattr(auth_client, method)(f"/api/adventures/{session_id}/suggestions")
    assert response.status_code == 404
    suggestion_model[0].aexecute_simple_task.assert_not_awaited()


async def test_refresh_accepts_legacy_cyrillic_session_ids(auth_client, suggestion_model):
    session_id = "русская-сессия-1234abcd"
    async with TestSessionLocal() as db:
        original = await db.get(GameSession, "portrait-session")
        session = GameSession(
            id=session_id,
            user_id=original.user_id,
            avatar_id=original.avatar_id,
            template_id=original.template_id,
            content_language="Russian",
        )
        db.add(session)
        db.add(
            SessionState(
                session_id=session_id,
                avatar_id=original.avatar_id,
                template_id=original.template_id,
                user_id=original.user_id,
                current_scene_id="TOWER",
            )
        )
        await db.commit()
    response = await auth_client.post(f"/api/adventures/{session_id}/suggestions")
    assert response.status_code == 200, response.text
    assert response.json()["suggestions"] == NEW


async def test_automatic_turn_suggestions_still_have_localized_fallback(suggestion_model):
    from backend.api.routes.adventures.gameplay_logic import GameTurnManager

    suggestion_model[0].aexecute_simple_task.side_effect = RuntimeError("offline")
    async with TestSessionLocal() as db:
        state = await state_for(db)
        session = await db.get(GameSession, state.session_id)
        user = await db.get(User, session.user_id)
        manager = GameTurnManager(db, state.session_id, user)
        assert await manager.initialize()
        ideas = await manager.suggestions.generate_prompt_suggestions("")
        assert len(ideas) >= 3
        assert any("а" in idea for idea in ideas)
        assert TurnSuggestionsManager.extract_prompt_suggestions(state.exit_states) == ideas
