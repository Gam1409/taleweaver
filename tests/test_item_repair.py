"""Explicit repairs preserve identity, possession, unrelated properties and old images."""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from backend.engine import item_repair
from backend.engine.item_repair_contracts import RepairValues
from backend.engine.visual_novel.concurrency import session_write_lease
from backend.models.adventure_template import AdventureTemplate
from backend.models.session_state import SessionState
from backend.models.turn_replay import TurnReplay
from backend.models.world_entity import WorldEntity
from tests.conftest import TestSessionLocal
from tests.test_chpm_api import chpm_world, portrait_world

__all__ = ["chpm_world", "portrait_world"]
PATH = "/api/adventures/portrait-session/items/COAT/repair"
GARMENT = {
    "category": "clothing",
    "layer": 3,
    "coverage": ["torso", "arms"],
    "opaque": True,
    "underwear": False,
    "description": "White coat",
}
ITEM = {
    "id": "COAT",
    "name": "White coat",
    "description": "A white coat.",
    "item_type": "WEARABLE",
    "wearable_slots": ["Chest"],
    "clothing": GARMENT,
    "image_url": "/data/old.png",
    "custom_origin": "keep",
    "weight": 2,
}


@pytest.fixture
async def repair_world(chpm_world):
    async with TestSessionLocal() as db:
        state = await db.scalar(
            select(SessionState).where(SessionState.session_id == "portrait-session")
        )
        state.is_debug_enabled = True
        state.entity_states = {
            **state.entity_states,
            "NPC_NEW": {
                "inventory": [deepcopy(ITEM)],
                "visual_profile": {"version": 1, "appearance": {}, "worn": [{"item_id": "COAT"}]},
            },
        }
        db.add(
            WorldEntity(
                id="COAT",
                session_id="portrait-session",
                entity_type="OBJECT",
                name=ITEM["name"],
                description=ITEM["description"],
                item_type="WEARABLE",
                current_scene_id="INVENTORY",
                metadata_json={
                    "clothing": GARMENT,
                    "wearable_slots": ["Chest"],
                    "script_marker": "keep",
                },
            )
        )
        await db.commit()


def values(**updates):
    return RepairValues.model_validate(
        {
            key: ITEM[key]
            for key in ("name", "description", "item_type", "wearable_slots", "clothing")
        }
        | updates
    )


async def read_record():
    async with TestSessionLocal() as db:
        state = await db.scalar(
            select(SessionState).where(SessionState.session_id == "portrait-session")
        )
        return deepcopy(state.entity_states)


async def test_preview_never_mutates_and_text_apply_updates_all_current_copies(
    auth_client, repair_world, monkeypatch
):
    before = await read_record()
    baseline = (await auth_client.get(PATH)).json()
    draft = values(
        description="The crisp white fabric falls in clean folds. Neat seams frame the coat’s practical cut, preserving its understated clinical appearance."
    )
    mocked = AsyncMock(return_value=draft)
    monkeypatch.setattr(item_repair, "propose", mocked)
    preview = await auth_client.post(
        PATH + "/preview", json={"before_hash": baseline["before_hash"]}
    )
    assert preview.status_code == 200, preview.text
    assert await read_record() == before
    response = await auth_client.post(
        PATH + "/apply",
        json={
            "before_hash": baseline["before_hash"],
            "values": preview.json()["values"],
            "parts": ["text"],
        },
    )
    assert response.status_code == 200, response.text
    after = await read_record()
    changed = after["NPC_NEW"]["inventory"][0]
    assert changed["description"] == draft.description
    assert changed["id"] == "COAT" and changed["custom_origin"] == "keep" and changed["weight"] == 2
    assert changed["clothing"] == GARMENT and changed["image_url"] == "/data/old.png"
    assert after["NPC_NEW"]["visual_profile"] == before["NPC_NEW"]["visual_profile"]
    assert after["COAT"]["vn_item_data"]["description"] == draft.description
    async with TestSessionLocal() as db:
        row = await db.scalar(
            select(WorldEntity).where(
                WorldEntity.session_id == "portrait-session", WorldEntity.id == "COAT"
            )
        )
        assert row.description == draft.description and row.metadata_json["script_marker"] == "keep"
        assert (
            await db.get(AdventureTemplate, "portrait-template")
        ).npc_personality_settings is None


async def test_stale_preview_and_busy_session_reject_before_writes(auth_client, repair_world):
    old = (await auth_client.get(PATH)).json()["before_hash"]
    body = {"before_hash": old, "values": values().model_dump(), "parts": ["text"]}
    with session_write_lease("portrait-session"):
        assert (await auth_client.post(PATH + "/apply", json=body)).status_code == 409
    async with TestSessionLocal() as db:
        state = await db.scalar(
            select(SessionState).where(SessionState.session_id == "portrait-session")
        )
        changed = deepcopy(state.entity_states)
        changed["NPC_NEW"]["inventory"][0]["description"] = "Changed elsewhere."
        state.entity_states = changed
        await db.commit()
    assert (await auth_client.post(PATH + "/apply", json=body)).status_code == 409
    assert (await read_record())["NPC_NEW"]["inventory"][0]["description"] == "Changed elsewhere."


async def test_image_failure_keeps_previous_image_and_no_other_section_is_written(
    auth_client, repair_world, monkeypatch
):
    before = await read_record()
    baseline = (await auth_client.get(PATH)).json()
    monkeypatch.setattr(
        item_repair, "generate_image", AsyncMock(side_effect=ValueError("Unavailable image server"))
    )
    response = await auth_client.post(
        PATH + "/image", json={"before_hash": baseline["before_hash"]}
    )
    assert response.status_code >= 400
    assert await read_record() == before


async def test_image_preview_uses_object_workflow_and_portable_session_storage(monkeypatch):
    t2i = {
        "simple_model_provider": "stable_diffusion",
        "simple_model": "item-checkpoint",
        "simple_min_long_edge": 512,
        "image_format": "png",
    }
    monkeypatch.setattr(
        item_repair, "session_image_settings", AsyncMock(return_value=(t2i, "grey tones", "quiet"))
    )
    generate = AsyncMock(return_value="/data/adventures/sessions/session/visuals/entities/item.png")
    monkeypatch.setattr(item_repair.MediaEngine, "generate_image", generate)
    db = SimpleNamespace(commit=AsyncMock())
    context = SimpleNamespace(
        read=lambda: ITEM, state=SimpleNamespace(session_id="session"), item_id="COAT"
    )
    assert await item_repair.generate_image(db, context, SimpleNamespace(encrypted_api_keys={}))
    request = generate.call_args.kwargs
    assert "/adventures/sessions/session/visuals/entities" in request["target_dir"].replace(
        "\\", "/"
    )
    assert request["provider_options"]["image_purpose"] == "object"
    assert request["provider_options"]["visual_target_type"] == "object"
    assert request["provider_options"]["width"] == request["provider_options"]["height"]
    db.commit.assert_awaited_once()


async def test_foreign_session_missing_item_and_debug_gate(auth_client, repair_world, monkeypatch):
    from backend.core.config import settings

    assert (
        await auth_client.get(PATH.replace("portrait-session", "other-session"))
    ).status_code == 404
    assert (await auth_client.get(PATH.replace("COAT", "NOT_HERE"))).status_code == 404
    monkeypatch.setattr(settings, "TALEWEAVER_DEBUG_ENABLED", False)
    async with TestSessionLocal() as db:
        state = await db.scalar(
            select(SessionState).where(SessionState.session_id == "portrait-session")
        )
        state.is_debug_enabled = False
        await db.commit()
    assert (await auth_client.get(PATH)).status_code == 403


async def test_invalid_technical_repair_cannot_corrupt_worn_references(auth_client, repair_world):
    before = await read_record()
    baseline = (await auth_client.get(PATH)).json()
    broken = values(item_type="DEFAULT", clothing=None, wearable_slots=[])
    response = await auth_client.post(
        PATH + "/apply",
        json={
            "before_hash": baseline["before_hash"],
            "values": broken.model_dump(),
            "parts": ["technical"],
        },
    )
    assert response.status_code == 422, response.text
    assert await read_record() == before


async def test_unselected_broken_metadata_cannot_block_a_text_only_repair(
    auth_client, repair_world
):
    baseline = (await auth_client.get(PATH)).json()
    response = await auth_client.post(
        PATH + "/apply",
        json={
            "before_hash": baseline["before_hash"],
            "parts": ["text"],
            "values": {
                "name": "White coat",
                "description": "The white coat falls in neat, carefully pressed folds.",
                "clothing": "broken legacy metadata",
                "item_type": "UNKNOWN_LEGACY_TYPE",
            },
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["item"]["clothing"] == GARMENT


@pytest.mark.parametrize("status", ["ready", "pending", "replaying", "executing"])
async def test_manual_repair_cannot_be_silently_undone_by_stale_turn_replay(
    auth_client, repair_world, status
):
    async with TestSessionLocal() as db:
        db.add(
            TurnReplay(session_id="portrait-session", before={}, input_text="Hello", status=status)
        )
        await db.commit()
    baseline = (await auth_client.get(PATH)).json()
    response = await auth_client.post(
        PATH + "/apply",
        json={
            "before_hash": baseline["before_hash"],
            "parts": ["text"],
            "values": values(
                description="A carefully pressed coat with neat white seams."
            ).model_dump(),
        },
    )
    assert response.status_code == (200 if status == "ready" else 409), response.text
    if status == "ready":
        assert response.json()["replay_invalidated"]
        async with TestSessionLocal() as db:
            assert (await db.get(TurnReplay, "portrait-session")).status == "edited"


async def test_inner_flag_cannot_be_cleared_to_bypass_policy_but_text_can_be_fixed(
    auth_client, repair_world
):
    async with TestSessionLocal() as db:
        state = await db.scalar(
            select(SessionState).where(SessionState.session_id == "portrait-session")
        )
        changed = deepcopy(state.entity_states)
        changed["NPC_NEW"]["inventory"][0]["name"] = "Red bra"
        state.entity_states = changed
        await db.commit()
    baseline = (await auth_client.get(PATH)).json()
    draft = values(name="Red bra", description="A neatly finished red garment.")
    body = {
        "before_hash": baseline["before_hash"],
        "values": draft.model_dump(),
        "parts": ["technical"],
    }
    assert (await auth_client.post(PATH + "/apply", json=body)).status_code == 422
    body["parts"] = ["text"]
    assert (await auth_client.post(PATH + "/apply", json=body)).status_code == 200
