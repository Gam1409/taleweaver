"""Scene inspection exposes saved evidence without rebuilding or leaking other sessions."""

from copy import deepcopy

import pytest
from sqlalchemy import delete, select

from backend.core.config import settings
from backend.core.llm_router import GameMasterLLM
from backend.engine.scene_illustrations.snapshots import REGISTRY_KEY
from backend.engine.scene_staging.state import KEY, digest
from backend.models.chat import ChatMessage
from backend.models.session_state import SessionState
from tests.conftest import TestSessionLocal
from tests.test_scene_illustrations import illustration_world

__all__ = ["illustration_world"]


async def enable_debug():
    async with TestSessionLocal() as db:
        state = await db.scalar(select(SessionState).where(SessionState.session_id == "moment"))
        # The shared illustration fixture inserts an undated legacy reply after its real moment.
        await db.execute(
            delete(ChatMessage).where(
                ChatMessage.id == "old-reply", ChatMessage.session_id == "moment"
            )
        )
        state.is_debug_enabled = True
        await db.commit()


@pytest.mark.asyncio
async def test_requires_owner_and_debug(auth_client, illustration_world, monkeypatch):
    monkeypatch.setattr(settings, "TALEWEAVER_DEBUG_ENABLED", False)
    assert (await auth_client.get("/api/adventures/foreign/scene-debug")).status_code == 404
    assert (await auth_client.get("/api/adventures/moment/scene-debug")).status_code == 403
    await enable_debug()
    assert (
        await auth_client.get("/api/adventures/moment/scene-debug?message_id=foreign-reply")
    ).status_code == 404


@pytest.mark.asyncio
async def test_reports_real_snapshot_and_disabled_staging_without_mutation(
    auth_client, illustration_world, monkeypatch
):
    await enable_debug()

    def forbidden(*args, **kwargs):
        raise AssertionError("Debug inspection must not call a model")

    monkeypatch.setattr(GameMasterLLM, "for_role", forbidden)
    async with TestSessionLocal() as db:
        state = await db.scalar(select(SessionState).where(SessionState.session_id == "moment"))
        before = deepcopy(state.entity_states)
    response = await auth_client.get("/api/adventures/moment/scene-debug")
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["staging_status"] == "disabled"
    assert data["selected_message"]["snapshot_status"] == "matches_message", data["messages"]
    assert data["snapshot"] == before[REGISTRY_KEY]["snapshots"]["moment-reply"]
    assert data["snapshot"]["visible_facts"]["characters"][0]["name"] == "Лина"
    assert data["cached_plans"] == []
    assert data["current_scene"]["label"] == "Cafe"
    async with TestSessionLocal() as db:
        state = await db.scalar(select(SessionState).where(SessionState.session_id == "moment"))
        assert state.entity_states == before


@pytest.mark.asyncio
async def test_distinguishes_missing_stale_and_unconfirmed(auth_client, illustration_world):
    await enable_debug()
    async with TestSessionLocal() as db:
        state = await db.scalar(select(SessionState).where(SessionState.session_id == "moment"))
        message = await db.get(ChatMessage, "moment-reply")
        message.content = "Changed narration."
        state.entity_states = {
            **state.entity_states,
            "__vn_settings__": {"scene_staging": True},
            KEY: {
                "scene_id": "CAFE",
                "source_hash": digest(message.content),
                "status": "unconfirmed",
                "rejected": 2,
                "actors": {},
            },
        }
        await db.commit()
    data = (await auth_client.get("/api/adventures/moment/scene-debug")).json()
    assert data["selected_message"]["snapshot_status"] == "stale"
    assert data["staging_status"] == "unconfirmed" and data["staging"]["rejected"] == 2
    async with TestSessionLocal() as db:
        state = await db.scalar(select(SessionState).where(SessionState.session_id == "moment"))
        db.add(
            ChatMessage(
                id="new-moment", session_id="moment", role="assistant", content="New moment."
            )
        )
        await db.commit()
    data = (await auth_client.get("/api/adventures/moment/scene-debug")).json()
    assert data["selected_message"]["id"] == "new-moment"
    assert data["selected_message"]["snapshot_status"] == "missing"
    assert data["snapshot"] is None and data["staging_status"] == "stale"
    older = (
        await auth_client.get("/api/adventures/moment/scene-debug?message_id=moment-reply")
    ).json()
    assert older["selected_message"]["id"] == "moment-reply"
    assert older["snapshot"] is not None


@pytest.mark.asyncio
async def test_empty_session_and_plans_are_scoped_to_selected_message(
    auth_client, illustration_world
):
    await enable_debug()
    async with TestSessionLocal() as db:
        state = await db.scalar(select(SessionState).where(SessionState.session_id == "moment"))
        state.entity_states = {
            **state.entity_states,
            "__visual_preparation__": {
                "entries": {
                    "own": {"message_id": "moment-reply", "plan": {"characters": []}},
                    "other": {
                        "message_id": "different-message",
                        "plan": {"characters": ["not selected"]},
                    },
                }
            },
        }
        await db.commit()
    data = (await auth_client.get("/api/adventures/moment/scene-debug")).json()
    assert [row["cache_key"] for row in data["cached_plans"]] == ["own"]
    async with TestSessionLocal() as db:
        message = await db.get(ChatMessage, "moment-reply")
        await db.delete(message)
        await db.commit()
    data = (await auth_client.get("/api/adventures/moment/scene-debug")).json()
    assert data["messages"] == [] and data["selected_message"] is None
    assert data["snapshot"] is None and data["cached_plans"] == []
