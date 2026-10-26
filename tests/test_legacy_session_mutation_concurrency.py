"""Legacy template routes mutate captured sessions without racing active turns."""

from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from backend.api.routes.adventures import legacy_session_mutations as legacy
from backend.engine.memory_rag.store import LanceMemoryStore
from backend.engine.visual_novel.concurrency import session_write_lease
from backend.models.chat import ChatMessage
from backend.models.game_session import GameSession
from backend.models.memory_rag import MemoryIndexState
from backend.models.session_state import SessionState
from tests.conftest import TestSessionLocal
from tests.test_session_portraits import portrait_world

__all__ = ["portrait_world"]


@pytest.mark.parametrize("operation", ["state", "pause", "resume", "reset"])
async def test_legacy_mutation_rejects_busy_captured_session(
    auth_client, portrait_world, operation
):
    if operation == "resume":
        async with TestSessionLocal() as db:
            (await db.get(GameSession, "portrait-session")).status = "paused"
            await db.commit()
    with session_write_lease("portrait-session"):
        path = f"/api/adventures/portrait-template/{operation}"
        response = (
            await auth_client.patch(path, json={"scene_id": "OTHER"})
            if operation == "state"
            else await auth_client.post(path)
        )
    assert response.status_code == 409
    async with TestSessionLocal() as db:
        assert await db.get(GameSession, "portrait-session") is not None
        state = await db.scalar(
            select(SessionState).where(SessionState.session_id == "portrait-session")
        )
        assert state.current_scene_id == "TOWER"


async def test_legacy_status_and_state_updates_work_when_idle(auth_client, portrait_world):
    response = await auth_client.patch(
        "/api/adventures/portrait-template/state", json={"in_game_time": 500}
    )
    assert response.status_code == 200 and response.json()["in_game_time"] == 500
    response = await auth_client.post("/api/adventures/portrait-template/pause")
    assert response.status_code == 200 and response.json()["status"] == "paused"
    response = await auth_client.post("/api/adventures/portrait-template/resume")
    assert response.status_code == 200 and response.json()["status"] == "active"


async def test_reset_purges_memory_and_captured_children_but_not_new_session(
    auth_client, portrait_world, monkeypatch
):
    cleanup = AsyncMock()
    monkeypatch.setattr(LanceMemoryStore, "delete_session", cleanup)
    async with TestSessionLocal() as db:
        owner = (await db.get(GameSession, "portrait-session")).user_id
        db.add(
            MemoryIndexState(
                session_id="portrait-session", user_id=owner, template_id="portrait-template"
            )
        )
        db.add(ChatMessage(session_id="portrait-session", role="assistant", content="Old story"))
        await db.commit()
    original = legacy._purge_captured_sessions

    async def create_new_after_selection(db, targets, identifiers):
        db.add(
            GameSession(
                id="new-session",
                user_id=owner,
                avatar_id="portrait-avatar",
                template_id="portrait-template",
            )
        )
        await db.flush()
        await original(db, targets, identifiers)

    monkeypatch.setattr(legacy, "_purge_captured_sessions", create_new_after_selection)
    response = await auth_client.post("/api/adventures/portrait-template/reset")
    assert response.status_code == 200, response.text
    async with TestSessionLocal() as db:
        assert await db.get(GameSession, "portrait-session") is None
        assert await db.get(GameSession, "new-session") is not None
        assert await db.get(MemoryIndexState, "portrait-session") is None
        assert (
            await db.scalar(select(ChatMessage).where(ChatMessage.session_id == "portrait-session"))
            is None
        )
    cleanup.assert_any_await(owner, "portrait-session")
