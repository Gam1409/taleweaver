"""Completed wardrobe changes carry canonical identity, including a just-removed garment."""

import json
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from backend.engine.clothing.context import build_clothing_context
from backend.engine.clothing.narration import narration_clothing
from backend.engine.clothing.planning import validate_plan
from backend.engine.clothing.resolution_facts import item_facts
from backend.engine.clothing.runtime import apply_wardrobe
from backend.engine.gameplay.manager import GameTurnManager
from backend.engine.rule_engine import GameEvent
from backend.engine.visual_novel.intent import VNProgressionIntent
from backend.models.world_entity import WorldEntity
from tests.conftest import TestSessionLocal
from tests.test_clothing_runtime import ClothingRoles, action, creation, profile, world
from tests.test_vn_turn_integration import install_roles, seed_vn

INNER = {"layer": 0, "coverage": ["pelvis"], "underwear": True, "opaque": True}
OUTER = {"layer": 1, "coverage": ["pelvis", "legs"], "opaque": True}
RED = "Red silk with narrow edging and carefully finished seams."
ACT = "Anna takes off the garment."


def scenario(detailed=True, age=30):
    manager, npc, scenes = world()
    manager.state.entity_states = {
        "__manifest_snapshot__": {
            "original_manifest": {
                "clothing_settings": {"detailed": detailed},
            }
        }
    }
    npc.visual_profile = profile("INNER", "OUTER")
    npc.visual_profile["appearance"]["age_years"] = age
    npc.inventory = [
        {
            "id": "INNER",
            "name": "STALE_NAME",
            "description": "PRIVATE_BLUE_CACHE",
            "clothing": INNER,
        },
        "OUTER",
    ]
    objects = [
        SimpleNamespace(
            id=identifier,
            name=name,
            description=description,
            entity_type="OBJECT",
            metadata_json={"clothing": garment},
            current_scene_id="ROOM",
            is_hidden=False,
            is_in_inventory=True,
        )
        for identifier, name, description, garment in (
            ("INNER", "Silk briefs", RED, INNER),
            ("OUTER", "Jeans", "Dark denim with reinforced stitching.", OUTER),
        )
    ]
    entities = [npc, *objects]
    manager.db.scalars = AsyncMock(return_value=SimpleNamespace(all=lambda: entities))
    return manager, npc, scenes, entities


def completed(event):
    text = event.narrative_description.split(
        "AUTHORITATIVE CLOTHING RESOLUTION (internal IDs, do not print): ", 1
    )[1]
    return json.JSONDecoder().raw_decode(text)[0]["completed"]


@pytest.mark.parametrize(
    "detailed,age,disclosed",
    [(True, 30, True), (False, 30, False), (True, None, False), (True, 17, False)],
)
async def test_removal_resolves_canonical_color_but_respects_inner_detail_preferences(
    detailed, age, disclosed
):
    manager, npc, scenes, entities = scenario(detailed, age)
    change = action(
        actor_id=npc.id,
        item_id="INNER",
        operation="remove",
        evidence=ACT,
        agency="npc_choice",
        npc_decision="approved",
    )
    event = GameEvent()
    event._vn_clothing_plan = validate_plan(
        manager, VNProgressionIntent(wardrobe_actions=[change]), ACT, "", entities, scenes
    )
    assert event._vn_clothing_plan.actions
    await apply_wardrobe(manager, event, manager.state.entity_states)
    rows = completed(event)
    assert len(rows) == 1 and rows[0]["item_id"] == "INNER" and rows[0]["operation"] == "remove"
    if disclosed:
        assert rows[0]["name"] == "Silk briefs" and rows[0]["description"] == RED
    else:
        assert (
            RED not in event.narrative_description
            and "Silk briefs" not in event.narrative_description
        )
    assert "PRIVATE_BLUE_CACHE" not in event.narrative_description
    assert [
        entry["item_id"] for entry in manager.state.entity_states[npc.id]["visual_profile"]["worn"]
    ] == ["OUTER"]
    _, visible = narration_clothing(manager, [npc], entities)
    assert RED not in visible  # The removed, carried item is no longer a visible worn layer.
    assert entities[1].description == RED


def test_continuity_keeps_canonical_names_without_copying_every_full_description():
    manager, npc, scenes, entities = scenario()
    before = deepcopy(npc.inventory)
    context = build_clothing_context(manager, entities, scenes)
    actor = next(row for row in context["actors"] if row["id"] == npc.id)
    garment = next(row for row in actor["owned_garments"] if row["id"] == "INNER")
    assert garment["name"] == "Silk briefs"
    assert "description" not in garment
    assert npc.inventory == before


async def test_rejected_removal_does_not_publish_private_item_details():
    manager, npc, scenes, entities = scenario()
    change = action(
        actor_id=npc.id,
        item_id="NOT_OWNED",
        operation="remove",
        evidence=ACT,
        agency="npc_choice",
        npc_decision="approved",
    )
    event = GameEvent()
    event._vn_clothing_plan = validate_plan(
        manager, VNProgressionIntent(wardrobe_actions=[change]), ACT, "", entities, scenes
    )
    await apply_wardrobe(manager, event, manager.state.entity_states)
    assert completed(event) == []
    assert RED not in event.narrative_description


def test_legacy_garment_description_respects_classification_when_the_flag_is_wrong():
    item = {
        "name": "Red silk briefs",
        "description": "",
        "clothing": {
            **INNER,
            "underwear": False,
            "description": RED,
        },
    }
    assert item_facts(item, include_inner=False) == {}
    assert item_facts(item, include_inner=True)["description"] == RED


async def test_completed_creation_carries_its_description_without_changing_other_items():
    manager, npc, scenes = world()
    made = creation(description="Crimson wool with a narrow woven fringe.")
    event = GameEvent()
    event._vn_clothing_plan = validate_plan(
        manager, VNProgressionIntent(garment_creations=[made]), made.evidence, "", [npc], scenes
    )
    await apply_wardrobe(manager, event, manager.state.entity_states)
    rows = completed(event)
    assert len(rows) == 1
    assert rows[0]["name"] == made.name and rows[0]["description"] == made.description
    assert npc.inventory[0]["name"] == "Green hat"


async def test_real_narrator_request_keeps_removed_item_description(monkeypatch):
    class Roles(ClothingRoles):
        async def structured(self, *args, **kwargs):
            result = await super().structured(*args, **kwargs)
            if type(result).__name__.startswith("VNProgressionIntent"):
                result.wardrobe_actions = [
                    action(
                        actor_id="LINA",
                        item_id="INNER",
                        operation="remove",
                        evidence=ACT,
                        agency="npc_choice",
                        npc_decision="approved",
                    )
                ]
            return result

    roles = Roles()
    install_roles(monkeypatch, roles)
    async with TestSessionLocal() as db:
        user, _, state, _ = await seed_vn(db)
        snapshot = deepcopy(state.entity_states.get("__manifest_snapshot__") or {})
        snapshot["original_manifest"] = {
            **snapshot.get("original_manifest", {}),
            "clothing_settings": {"detailed": True},
        }
        state.entity_states = {**state.entity_states, "__manifest_snapshot__": snapshot}
        npc = await db.scalar(
            select(WorldEntity).where(
                WorldEntity.session_id == "session-1", WorldEntity.id == "LINA"
            )
        )
        npc.inventory = ["INNER", "OUTER"]
        npc.visual_profile = profile("INNER", "OUTER")
        for identifier, name, description, garment in (
            ("INNER", "Silk briefs", RED, INNER),
            ("OUTER", "Jeans", "Dark denim.", OUTER),
        ):
            db.add(
                WorldEntity(
                    id=identifier,
                    name=name,
                    description=description,
                    entity_type="OBJECT",
                    item_type="WEARABLE",
                    template_id=state.template_id,
                    session_id="session-1",
                    current_scene_id="START",
                    is_in_inventory=True,
                    metadata_json={"clothing": garment},
                )
            )
        await db.commit()
        events = [event async for event in GameTurnManager(db, "session-1", user).process_turn(ACT)]
        assert any(event.startswith("event: final") for event in events), "".join(events)
        request = str(roles.prompts[-1])
        assert "AUTHORITATIVE CLOTHING RESOLUTION" in request
        assert RED in request and "Silk briefs" in request
