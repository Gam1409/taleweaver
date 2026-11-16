"""Ownership must hold on every session-state resolution path, including legacy IDs."""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select

from backend.api.routes.adventures.logic import AdventureLogic
from backend.core.llm_router import GameMasterLLM
from backend.models.adventure_template import AdventureTemplate
from backend.models.avatar import Avatar
from backend.models.chat import ChatMessage
from backend.models.game_session import GameSession
from backend.models.session_state import SessionState
from backend.models.user import User
from tests.conftest import TestSessionLocal


@pytest.fixture
async def access_world(auth_client, monkeypatch):
    model = AsyncMock(side_effect=AssertionError("Session authorization must not call a model"))
    monkeypatch.setattr(GameMasterLLM, "aexecute_simple_task", model)
    monkeypatch.setattr(GameMasterLLM, "aexecute_complex_task", model)
    async with TestSessionLocal() as db:
        owner = await db.scalar(select(User).where(User.username == "test_user"))
        owner.role = "user"
        other = User(username="other-session-owner", hashed_password=owner.hashed_password)
        db.add(other)
        await db.flush()
        db.add(AdventureTemplate(id="SHARED", owner_id=owner.id, title="Shared adventure"))
        for user, key in ((owner, "own"), (other, "other")):
            db.add(Avatar(id=f"hero-{key}", user_id=user.id, template_id="SHARED", name=key))
        await db.flush()
        for user, key in ((owner, "own"), (other, "other")):
            db.add(
                GameSession(
                    id=f"session-{key}",
                    user_id=user.id,
                    avatar_id=f"hero-{key}",
                    template_id="SHARED",
                    updated_at=datetime.now(timezone.utc) + timedelta(minutes=key == "other"),
                )
            )
        await db.flush()
        for user, key in ((owner, "own"), (other, "other")):
            db.add(
                SessionState(
                    id=f"state-{key}",
                    session_id=f"session-{key}",
                    user_id=user.id,
                    template_id="SHARED",
                    avatar_id=f"hero-{key}",
                    current_scene_id="START",
                    is_debug_enabled=True,
                    walkthrough=f"Private walkthrough {key}",
                    is_walkthrough_revealed=True,
                    entity_states={},
                )
            )
        await db.commit()
        return owner.id, other.id, model


@pytest.mark.parametrize("role", ["user", "admin"])
@pytest.mark.parametrize("endpoint", ["chat", "session-debug", "walkthrough"])
async def test_foreign_state_read_is_denied_before_payload(
    auth_client, access_world, role, endpoint
):
    owner_id, _, model = access_world
    async with TestSessionLocal() as db:
        owner = await db.get(User, owner_id)
        owner.role = role
        await db.commit()
    response = await auth_client.get(f"/api/adventures/session-other/{endpoint}")
    assert response.status_code == 404, response.text
    assert "Private walkthrough other" not in response.text
    assert "hero-other" not in response.text
    model.assert_not_awaited()


async def test_foreign_chat_cannot_change_state_or_append_history(auth_client, access_world):
    _, _, model = access_world
    response = await auth_client.post(
        "/api/adventures/session-other/chat", json={"content": "/debug off"}
    )
    assert response.status_code in {200, 404}
    async with TestSessionLocal() as db:
        foreign = await db.get(SessionState, "state-other")
        assert foreign.is_debug_enabled is True
        assert await db.scalar(select(func.count()).select_from(ChatMessage)) == 0
    assert "hero-other" not in response.text
    model.assert_not_awaited()


@pytest.mark.parametrize("heal", [False, True])
async def test_owner_and_legacy_template_resolution_never_select_foreign_session(
    auth_client, access_world, heal
):
    owner_id, _, model = access_world
    async with TestSessionLocal() as db:
        if heal:
            await db.delete(await db.get(SessionState, "state-own"))
            await db.commit()
        state = await AdventureLogic.resolve_session_state(db, "SHARED", user_id=owner_id)
        assert state is not None and state.session_id == "session-own"
        assert state.session.user_id == owner_id
        direct = await AdventureLogic.resolve_session_state(db, "session-own", user_id=owner_id)
        assert direct is state
    model.assert_not_awaited()


async def test_foreign_missing_state_is_not_auto_healed(auth_client, access_world):
    owner_id, _, model = access_world
    async with TestSessionLocal() as db:
        await db.delete(await db.get(SessionState, "state-other"))
        await db.commit()
        result = await AdventureLogic.resolve_session_state(db, "session-other", user_id=owner_id)
        assert result is None
        assert (
            await db.scalar(select(SessionState).where(SessionState.session_id == "session-other"))
            is None
        )
    model.assert_not_awaited()


async def test_session_owner_is_authoritative_over_denormalized_state_owner(
    auth_client, access_world
):
    owner_id, other_id, _ = access_world
    async with TestSessionLocal() as db:
        own = await db.get(SessionState, "state-own")
        foreign = await db.get(SessionState, "state-other")
        own.user_id, foreign.user_id = other_id, owner_id
        await db.commit()
        assert (
            await AdventureLogic.resolve_session_state(db, "session-other", user_id=owner_id)
            is None
        )
        assert (
            await AdventureLogic.resolve_session_state(db, "session-own", user_id=owner_id) is own
        )


@pytest.mark.parametrize("user_id", ["", None])
async def test_missing_owner_never_selects_an_unscoped_session(auth_client, access_world, user_id):
    async with TestSessionLocal() as db:
        for identifier in ("session-other", "SHARED"):
            assert (
                await AdventureLogic.resolve_session_state(db, identifier, user_id=user_id) is None
            )


async def test_state_without_a_session_cannot_grant_access(auth_client, access_world):
    owner_id, _, _ = access_world
    async with TestSessionLocal() as db:
        db.add(
            SessionState(session_id="orphan-session", user_id=owner_id, current_scene_id="START")
        )
        await db.commit()
        assert (
            await AdventureLogic.resolve_session_state(db, "orphan-session", user_id=owner_id)
            is None
        )


async def test_owner_walkthrough_and_debug_command_still_work(auth_client, access_world):
    response = await auth_client.get("/api/adventures/session-own/walkthrough")
    assert response.status_code == 200
    assert response.json()["walkthrough"] == "Private walkthrough own"
    response = await auth_client.post(
        "/api/adventures/session-own/chat", json={"content": "/debug off"}
    )
    assert response.status_code == 200
    async with TestSessionLocal() as db:
        assert (await db.get(SessionState, "state-own")).is_debug_enabled is False
