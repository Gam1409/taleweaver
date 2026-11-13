"""Replay requests emitted by the real creation modal and editor service."""

import json
from copy import deepcopy
from pathlib import Path

import pytest
from sqlalchemy import select

from backend.models.world_entity import WorldEntity
from tests.conftest import TestSessionLocal
from tests.editor_entity_creation_support import entity_creation_world

__all__ = ["entity_creation_world"]
pytestmark = pytest.mark.asyncio
REQUESTS = json.loads(
    (Path(__file__).parent / "fixtures" / "editor_creation_requests.json").read_text()
)
CREATES = [request for request in REQUESTS if request["method"] == "POST"]


@pytest.mark.parametrize("captured", CREATES, ids=[request["case"] for request in CREATES])
async def test_captured_modal_creation_persists_full_authored_payload(
    entity_creation_world, captured
):
    world = entity_creation_world
    payload = deepcopy(captured["data"])
    payload["scene_id"] = "HALL"
    response = await world.client.post(
        f"/api/adventures/{world.template_id}/editor/entity", json=payload
    )
    assert response.status_code == 200, response.text
    async with TestSessionLocal() as db:
        row = await db.scalar(
            select(WorldEntity).where(
                WorldEntity.template_id == world.template_id,
                WorldEntity.session_id.is_(None),
                WorldEntity.id == payload["entity_id"],
            )
        )
        assert row.spatial_position == payload.get("spatial_position")
        assert {
            key: row.metadata_json[key] for key in payload.get("metadata_json", {})
        } == payload.get("metadata_json", {})
        for key, value in payload.items():
            if key.endswith(("_script", "_text")):
                assert row.metadata_json[key] == value
        if payload["entity_type"] == "OBJECT":
            assert row.is_portable is payload["is_portable"]
            assert row.combination_ingredients == payload["combination_ingredients"]
        else:
            assert (row.hp, row.max_hp, row.stamina, row.max_stamina, row.mana, row.max_mana) == (
                0,
                0,
                0,
                0,
                0,
                0,
            )


async def test_captured_npc_zero_edit_preserves_zero_and_clears_callbacks(entity_creation_world):
    world = entity_creation_world
    creation = deepcopy(
        next(request["data"] for request in REQUESTS if request["case"] == "NPC_ZERO")
    )
    creation["scene_id"] = "HALL"
    response = await world.client.post(
        f"/api/adventures/{world.template_id}/editor/entity", json=creation
    )
    assert response.status_code == 200, response.text
    payload = deepcopy(
        next(request["data"] for request in REQUESTS if request["case"] == "NPC_ZERO_PATCH")
    )
    payload["target_id"] = creation["entity_id"]
    payload["new_id"] = creation["entity_id"]
    response = await world.client.patch(
        f"/api/adventures/{world.template_id}/editor/entity", json=payload
    )
    assert response.status_code == 200, response.text
    async with TestSessionLocal() as db:
        row = await db.scalar(
            select(WorldEntity).where(
                WorldEntity.template_id == world.template_id,
                WorldEntity.id == creation["entity_id"],
            )
        )
        assert (row.hp, row.stamina, row.mana) == (0, 0, 0)
        assert row.spatial_position is None
        assert all(
            row.metadata_json[key] == "" for key in payload if key.endswith(("_script", "_text"))
        )
