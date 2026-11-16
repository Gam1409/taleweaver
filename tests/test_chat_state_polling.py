"""State-only polls must not hydrate or serialize the complete session transcript."""

from unittest.mock import AsyncMock

from sqlalchemy import select

from backend.api.routes.adventures import gameplay
from backend.engine.visual_novel.concurrency import session_write_lease
from backend.models.game_session import GameSession
from backend.models.user import User
from tests.conftest import TestSessionLocal
from tests.test_vn_turn_integration import seed_vn


async def owned_session():
    async with TestSessionLocal() as db:
        _user, avatar, state, prior = await seed_vn(db)
        owner = await db.scalar(select(User).where(User.username == "test_user"))
        game = await db.get(GameSession, state.session_id)
        game.user_id = state.user_id = avatar.user_id = owner.id
        await db.commit()
        return state.session_id, prior


async def test_state_poll_skips_history_but_initial_load_preserves_it(auth_client, monkeypatch):
    session_id, prior = await owned_session()
    full = await auth_client.get(f"/api/adventures/{session_id}/chat")
    assert full.status_code == 200, full.text
    assert full.json()["history_included"] is True
    assert any(row["id"] == prior for row in full.json()["messages"])
    loader = AsyncMock(side_effect=AssertionError("A state poll must not load history"))
    monkeypatch.setattr(gameplay, "load_chat_history", loader)
    response = await auth_client.get(f"/api/adventures/{session_id}/chat?include_messages=false")
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["history_included"] is False and data["messages"] == []
    assert data["scene_id"] == full.json()["scene_id"]
    assert data["sheet"]["hp"] == full.json()["sheet"]["hp"]
    loader.assert_not_awaited()


async def test_state_only_flag_does_not_bypass_session_access(auth_client, monkeypatch):
    await owned_session()
    loader = AsyncMock(side_effect=AssertionError("Unauthorized history read"))
    monkeypatch.setattr(gameplay, "load_chat_history", loader)
    response = await auth_client.get("/api/adventures/not-owned/chat?include_messages=false")
    assert response.status_code == 404
    loader.assert_not_awaited()


async def test_busy_session_can_be_polled_without_loading_history(auth_client, monkeypatch):
    session_id, _prior = await owned_session()
    loader = AsyncMock(side_effect=AssertionError("No full transcript during a turn"))
    monkeypatch.setattr(gameplay, "load_chat_history", loader)
    with session_write_lease(session_id):
        response = await auth_client.get(
            f"/api/adventures/{session_id}/chat?include_messages=false"
        )
    assert response.status_code == 200, response.text
    assert response.json()["history_included"] is False
    loader.assert_not_awaited()
