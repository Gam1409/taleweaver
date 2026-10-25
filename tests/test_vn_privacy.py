"""Public VN surfaces reveal learned facts, not the private relationship simulation."""

from copy import deepcopy
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from backend.api.routes.adventures import gameplay, session_npcs
from backend.engine.visual_novel.config import SETTINGS_KEY
from backend.engine.visual_novel.schema import STATE_KEY
from backend.models.adventure_template import AdventureTemplate
from backend.models.session_state import SessionState
from backend.models.world_entity import WorldEntity
from tests.conftest import TestSessionLocal
from tests.test_session_portraits import portrait_world
from tests.test_vn_lifecycle import (
    PRIVATE_CORE,
    PRIVATE_GOAL,
    PRIVATE_MEMORY,
    SESSION,
    social_fixture,
    vn_world,
)

__all__ = ["portrait_world", "vn_world"]
AUTHORED_SECRETS = ["SECRET authored goal", "SECRET authored principles", "SECRET hidden key"]


async def test_public_chat_cards_and_settings_do_not_expose_private_social_state(
    auth_client, vn_world, monkeypatch
):
    async with TestSessionLocal() as db:
        npc = await db.scalar(
            select(WorldEntity).where(
                WorldEntity.session_id == SESSION, WorldEntity.id == "NPC_NEW"
            )
        )
        npc.goal, npc.character = AUTHORED_SECRETS[:2]
        npc.inventory = [{"name": AUTHORED_SECRETS[2]}]
        npc.metadata_json = {"secret_plan": "SECRET arbitrary metadata"}
        db.add(
            WorldEntity(
                id="UNMET_NPC",
                session_id=SESSION,
                entity_type="NPC",
                name="SECRET unmet character",
                description="SECRET unseen description",
                current_scene_id="TOWER",
                is_hidden=True,
            )
        )
        await db.commit()
    monkeypatch.setattr(gameplay, "resolve_prompt_suggestions", AsyncMock(return_value=[]))
    monkeypatch.setattr(gameplay, "schedule_npc_journal", lambda *_: None)
    monkeypatch.setattr(session_npcs, "schedule", lambda *_: None)
    for suffix in ("chat", "npcs", "npcs/NPC_NEW", "vn-settings"):
        response = await auth_client.get(f"/api/adventures/{SESSION}/{suffix}")
        assert response.status_code == 200, response.text
        for private in (
            PRIVATE_CORE,
            PRIVATE_GOAL,
            PRIVATE_MEMORY,
            STATE_KEY,
            *AUTHORED_SECRETS,
            "SECRET arbitrary metadata",
            "SECRET unmet character",
            "SECRET unseen description",
        ):
            assert private not in response.text, (suffix, private)
        assert '"processed_message_ids"' not in response.text
        assert '"next_intention"' not in response.text
    card = await auth_client.get(f"/api/adventures/{SESSION}/npcs/NPC_NEW")
    assert card.json()["narrative_role"] == "major"
    assert card.json()["description"] == "Scarred sailor in a blue coat"
    async with TestSessionLocal() as db:
        npc = await db.scalar(
            select(WorldEntity).where(
                WorldEntity.session_id == SESSION, WorldEntity.id == "NPC_NEW"
            )
        )
        assert npc.goal == AUTHORED_SECRETS[0]
        assert npc.character == AUTHORED_SECRETS[1]
        assert npc.inventory == [{"name": AUTHORED_SECRETS[2]}]


async def test_pace_changes_persist_without_modifying_private_simulation(auth_client, vn_world):
    response = await auth_client.get(f"/api/adventures/{SESSION}/vn-settings")
    assert response.json() == {"mode": "vn", "settings": {"pace": "leisurely"}}
    response = await auth_client.patch(
        f"/api/adventures/{SESSION}/vn-settings", json={"pace": "brisk"}
    )
    assert response.status_code == 200, response.text
    assert response.json() == {"mode": "vn", "settings": {"pace": "brisk"}}
    async with TestSessionLocal() as db:
        state = await db.scalar(select(SessionState).where(SessionState.session_id == SESSION))
        assert state.entity_states[STATE_KEY] == social_fixture().model_dump()
        assert state.entity_states[SETTINGS_KEY] == {"pace": "brisk"}


@pytest.mark.parametrize("session_id", ["other-session", "missing-session"])
async def test_settings_do_not_disclose_or_modify_another_players_session(
    auth_client, vn_world, session_id
):
    for method, fields in (("get", {}), ("patch", {"json": {"pace": "brisk"}})):
        response = await getattr(auth_client, method)(
            f"/api/adventures/{session_id}/vn-settings", **fields
        )
        assert response.status_code == 404
    async with TestSessionLocal() as db:
        other = await db.scalar(
            select(SessionState).where(SessionState.session_id == "other-session")
        )
        assert SETTINGS_KEY not in other.entity_states


@pytest.mark.parametrize(
    "payload",
    [
        {"pace": "instant"},
        {"pace": "brisk", STATE_KEY: {"characters": {}}},
        {"pace": "brisk", "trust": 100},
    ],
)
async def test_settings_reject_unknown_values_and_private_state_injection(
    auth_client, vn_world, payload
):
    async with TestSessionLocal() as db:
        state = await db.scalar(select(SessionState).where(SessionState.session_id == SESSION))
        before = deepcopy(state.entity_states)
    response = await auth_client.patch(f"/api/adventures/{SESSION}/vn-settings", json=payload)
    assert response.status_code == 422
    async with TestSessionLocal() as db:
        state = await db.scalar(select(SessionState).where(SessionState.session_id == SESSION))
        assert state.entity_states == before


async def test_settings_are_unavailable_for_existing_rpg_sessions(auth_client, portrait_world):
    async with TestSessionLocal() as db:
        template = await db.get(AdventureTemplate, "portrait-template")
        template.rule_enforcement_mode = "strict"
        await db.commit()
    for method, fields in (("get", {}), ("patch", {"json": {"pace": "brisk"}})):
        response = await getattr(auth_client, method)(
            f"/api/adventures/{SESSION}/vn-settings", **fields
        )
        assert response.status_code == 409
