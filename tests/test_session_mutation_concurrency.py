"""Direct state mutations share the game turn lease and fail before loading state."""

import pytest
from sqlalchemy import event, select

from backend.engine.visual_novel.concurrency import _active_sessions, session_write_lease
from backend.models.game_session import GameSession
from tests.conftest import TestSessionLocal, test_engine
from tests.test_session_portraits import portrait_world

__all__ = ["portrait_world"]


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("DELETE", "/sessions/{id}", None),
        ("DELETE", "/sessions/{id}/messages/missing", None),
        ("POST", "/sessions/{id}/copy", None),
        ("PATCH", "/sessions/{id}", {"status": "active"}),
        ("POST", "/sessions/{id}/checkpoints/missing/restore", None),
        ("POST", "/{id}/terminal-epilogue", {}),
        ("POST", "/{id}/text-logs/missing/read", None),
        ("POST", "/{id}/containers/missing/unlock", None),
        ("POST", "/{id}/exits/missing/unlock", None),
        ("POST", "/{id}/exits/missing/traverse", None),
    ],
)
async def test_active_turn_blocks_direct_session_mutations(
    auth_client, portrait_world, method, path, body
):
    session_id = "portrait-session"
    with session_write_lease(session_id):
        response = await auth_client.request(
            method, "/api/adventures" + path.format(id=session_id), json=body
        )
    assert response.status_code == 409
    assert "Wait for the current turn" in response.json()["detail"]
    assert session_id not in _active_sessions
    async with TestSessionLocal() as db:
        assert (
            await db.scalar(select(GameSession.id).where(GameSession.id == session_id))
            == session_id
        )


async def test_mutation_lease_does_not_disclose_foreign_busy_session(auth_client, portrait_world):
    with session_write_lease("foreign-session"):
        response = await auth_client.delete("/api/adventures/sessions/foreign-session")
    assert response.status_code == 404


async def test_failed_endpoint_releases_lease(auth_client, portrait_world):
    response = await auth_client.post(
        "/api/adventures/sessions/portrait-session/checkpoints/missing/restore"
    )
    assert response.status_code == 404
    assert "portrait-session" not in _active_sessions
    response = await auth_client.patch(
        "/api/adventures/sessions/portrait-session", json={"status": "active"}
    )
    assert response.status_code == 200
    assert "portrait-session" not in _active_sessions


async def test_chat_poll_during_turn_is_read_only(auth_client, portrait_world, monkeypatch):
    from unittest.mock import MagicMock

    from backend.api.routes.adventures import gameplay
    from backend.engine.memory_rag import worker as memory_worker

    monkeypatch.setattr(gameplay, "schedule_npc_journal", MagicMock())
    monkeypatch.setattr(memory_worker, "schedule", MagicMock())
    statements = []

    def capture(_connection, _cursor, statement, _parameters, _context, _many):
        statements.append(statement.lstrip().split(None, 1)[0].upper())

    event.listen(test_engine.sync_engine, "before_cursor_execute", capture)
    try:
        with session_write_lease("portrait-session"):
            response = await auth_client.get("/api/adventures/portrait-session/chat")
            assert response.status_code == 200, response.text
            assert not ({"INSERT", "UPDATE", "DELETE"} & set(statements))
    finally:
        event.remove(test_engine.sync_engine, "before_cursor_execute", capture)
    assert "portrait-session" not in _active_sessions


async def test_missing_chat_snapshot_releases_lease(auth_client):
    response = await auth_client.get("/api/adventures/missing-session/chat")
    assert response.status_code == 404
    assert "missing-session" not in _active_sessions
