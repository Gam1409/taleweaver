"""Gameplay snapshots accept nullable state fields from older saved sessions."""

import pytest
from sqlalchemy import select, update

from backend.models.session_state import SessionState
from tests.conftest import TestSessionLocal


@pytest.mark.asyncio
async def test_chat_snapshot_normalizes_null_completion_flag(auth_client):
    created = await auth_client.post(
        "/api/adventures/", json={"title": "Legacy completion flag", "avatar_name": "Hero"}
    )
    assert created.status_code == 201, created.text
    game_id = created.json()["game_id"]
    async with TestSessionLocal() as db:
        await db.execute(
            update(SessionState).where(SessionState.session_id == game_id).values(is_completed=None)
        )
        await db.commit()
        assert (
            await db.scalar(
                select(SessionState.is_completed).where(SessionState.session_id == game_id)
            )
            is None
        )

    response = await auth_client.get(f"/api/adventures/{game_id}/chat")
    assert response.status_code == 200, response.text
    assert response.json()["is_completed"] is False
