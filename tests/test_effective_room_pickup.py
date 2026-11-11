"""A room object's current custody and metadata survive a prior NPC inventory record."""

import json
from copy import deepcopy
from unittest.mock import MagicMock

import pytest
from sqlalchemy import select

from backend.engine.debug_engine import DebugEngine
from backend.engine.gameplay.manager import GameTurnManager
from backend.engine.gameplay.world import AdventureLogic
from backend.engine.visual_novel.continuity import possession_snapshot
from backend.models.world_entity import WorldEntity
from tests.conftest import TestSessionLocal
from tests.test_vn_turn_integration import seed_vn


async def seed_drop(db, *, base_scene="INVENTORY", hidden=False):
    user, avatar, state, _ = await seed_vn(db)
    state.is_debug_enabled = True
    garment = {
        "id": "COAT",
        "name": "White coat",
        "description": "A white linen coat.",
        "item_type": "WEARABLE",
        "image_url": "/data/coat.png",
        "clothing": {"layer": 2, "coverage": ["torso", "arms"]},
        "wearable_slots": ["Chest"],
    }
    world = WorldEntity(
        id="COAT",
        session_id=state.session_id,
        entity_type="OBJECT",
        name=garment["name"],
        description=garment["description"],
        current_scene_id=base_scene,
        is_in_inventory=True,
        is_hidden=hidden,
        is_portable=True,
        item_type="WEARABLE",
        metadata_json=deepcopy(garment),
    )
    db.add(world)
    state.entity_states = {
        **state.entity_states,
        "LINA": {
            "inventory": [garment],
            "visual_profile": {"appearance": {"age_years": 32}, "worn": [{"item_id": "COAT"}]},
        },
    }
    await db.commit()
    result = await DebugEngine.handle_debug_command(
        db,
        state,
        "npc_wardrobe "
        + json.dumps(
            {
                "npc_id": "LINA",
                "item_id": "COAT",
                "operation": "place",
                "spatial_position": "on the bed",
            }
        ),
        user=user,
        avatar=avatar,
    )
    assert "no longer carried or worn" in result, result
    await db.commit()
    return user, avatar, state, world, garment


@pytest.mark.parametrize(
    "base_scene,hidden", [("INVENTORY", False), ("START", True), ("FOREST", False)]
)
async def test_direct_take_uses_the_same_effective_room_item_as_the_scene_view(
    monkeypatch, base_scene, hidden
):
    monkeypatch.setattr(
        GameTurnManager,
        "_run_llm_cycle",
        MagicMock(side_effect=AssertionError("No inference for an ordinary direct pickup.")),
    )
    async with TestSessionLocal() as db:
        user, avatar, state, world, garment = await seed_drop(
            db, base_scene=base_scene, hidden=hidden
        )
        visible = await AdventureLogic.build_session_entities(db, state)
        assert "COAT" in {row["id"] for row in visible}
        parts = [
            part
            async for part in GameTurnManager(db, state.session_id, user).process_turn(
                "/take_direct COAT"
            )
        ]
        await db.refresh(avatar)
        picked = [row for row in avatar.inventory if row.get("id") == "COAT"]
        assert len(picked) == 1, "".join(parts)
        assert picked[0]["clothing"] == garment["clothing"]
        assert picked[0]["property_owner_id"] == "LINA"
        assert picked[0]["image_url"] == garment["image_url"]
        assert not picked[0].get("spatial_position")
        assert "COAT" not in {
            row["id"] for row in await AdventureLogic.build_session_entities(db, state)
        }
        assert world.is_in_inventory and world.current_scene_id == "INVENTORY"
        assert not state.entity_states["LINA"]["inventory"]


@pytest.mark.parametrize("fault", ["hidden", "carried", "elsewhere", "npc_held", "not_portable"])
async def test_direct_take_does_not_bypass_effective_availability_or_take_a_held_possession(
    monkeypatch, fault
):
    monkeypatch.setattr(
        GameTurnManager,
        "_run_llm_cycle",
        MagicMock(side_effect=AssertionError("No inference for direct pickup.")),
    )
    async with TestSessionLocal() as db:
        user, avatar, state, _, garment = await seed_drop(db)
        overrides = deepcopy(state.entity_states)
        if fault == "hidden":
            overrides["COAT"]["is_hidden"] = True
        if fault == "carried":
            overrides["COAT"]["is_in_inventory"] = True
        if fault == "elsewhere":
            overrides["COAT"]["current_scene_id"] = "FOREST"
        if fault == "npc_held":
            overrides["LINA"]["inventory"] = [garment]
        if fault == "not_portable":
            overrides["COAT"]["is_portable"] = False
        state.entity_states = overrides
        await db.commit()
        before = deepcopy(avatar.inventory)
        parts = [
            part
            async for part in GameTurnManager(db, state.session_id, user).process_turn(
                "/take_direct COAT"
            )
        ]
        assert "You cannot take that" in "".join(parts)
        assert avatar.inventory == before


async def test_unavailable_npc_possessions_cannot_reappear_as_room_objects():
    async with TestSessionLocal() as db:
        _, avatar, state, _, garment = await seed_drop(db)
        state.entity_states = {
            **state.entity_states,
            "LINA": {
                **state.entity_states["LINA"],
                "current_scene_id": "FOREST",
                "inventory": [garment],
            },
        }
        entities = list(
            await db.scalars(select(WorldEntity).where(WorldEntity.session_id == state.session_id))
        )
        host = type("Host", (), {"state": state, "avatar": avatar})()
        snapshot = possession_snapshot(host, entities)
        assert "COAT" not in snapshot.items


async def test_legacy_template_pickup_materializes_a_session_row_without_changing_the_template(
    monkeypatch,
):
    monkeypatch.setattr(
        GameTurnManager,
        "_run_llm_cycle",
        MagicMock(side_effect=AssertionError("No inference for direct pickup.")),
    )
    async with TestSessionLocal() as db:
        user, avatar, state, _ = await seed_vn(db)
        template = WorldEntity(
            id="TEMPLATE_KEY",
            template_id=state.template_id,
            entity_type="OBJECT",
            name="Key",
            description="A brass key.",
            current_scene_id="START",
            is_portable=True,
            is_hidden=False,
            is_in_inventory=False,
        )
        db.add(template)
        await db.commit()
        parts = [
            part
            async for part in GameTurnManager(db, state.session_id, user).process_turn(
                "/take_direct TEMPLATE_KEY"
            )
        ]
        assert "Added Key to your inventory" in "".join(parts), "".join(parts)
        await db.refresh(template)
        assert template.current_scene_id == "START" and not template.is_in_inventory
        session_item = await db.scalar(
            select(WorldEntity).where(
                WorldEntity.session_id == state.session_id, WorldEntity.id == "TEMPLATE_KEY"
            )
        )
        assert session_item is not None and session_item.pk != template.pk
        assert session_item.is_in_inventory
