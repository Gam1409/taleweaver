"""Explicit debug removal changes canonical wear, preserving item identity and ownership."""

import json
from copy import deepcopy

import pytest
from sqlalchemy import select

from backend.engine.debug_engine import DebugEngine
from backend.models.world_entity import WorldEntity
from tests.conftest import TestSessionLocal
from tests.test_vn_turn_integration import seed_vn


@pytest.mark.parametrize("body", [False, True])
async def test_debug_removes_wear_without_requiring_garment_editing_or_deleting_the_item(body):
    async with TestSessionLocal() as db:
        _, _, state, _ = await seed_vn(db)
        state.is_debug_enabled = True
        npc = await db.scalar(select(WorldEntity).where(WorldEntity.id == "LINA"))
        item = {"id": "COAT", "name": "White coat", "item_type": "WEARABLE"}
        if not body:
            item["clothing"] = {"layer": 3, "coverage": ["torso"]}
        worn = {"item_id": "COAT", **({"attachment_slot": "anal"} if body else {})}
        state.entity_states = {
            **state.entity_states,
            "LINA": {
                "inventory": [*npc.inventory, item],
                "marker": "preserve",
                "visual_profile": {"appearance": {"age_years": 30}, "worn": [worn]},
            },
        }
        before = deepcopy(state.entity_states["LINA"]["inventory"])
        minute = state.in_game_time
        args = "npc_unwear " + json.dumps({"npc_id": "LINA", "item_id": "COAT"})
        result = await DebugEngine.handle_debug_command(db, state, args)
        assert "remains in their inventory" in result
        await db.commit()
        await db.refresh(state)
        assert state.entity_states["LINA"]["inventory"] == before
        assert state.entity_states["LINA"]["visual_profile"]["worn"] == []
        assert state.entity_states["LINA"]["marker"] == "preserve"
        assert state.in_game_time == minute
        assert not npc.visual_profile and npc.inventory[0]["id"] == "HIDDEN_RING"
        assert "no longer recorded" in await DebugEngine.handle_debug_command(db, state, args)


async def test_debug_removal_rejects_disabled_debug_unknown_npc_and_unowned_items():
    async with TestSessionLocal() as db:
        _, _, state, _ = await seed_vn(db)
        args = "npc_unwear " + json.dumps({"npc_id": "LINA", "item_id": "COAT"})
        assert "Enable debug" in await DebugEngine.handle_debug_command(db, state, args)
        state.is_debug_enabled = True
        original = deepcopy(state.entity_states)
        assert "no longer recorded" in await DebugEngine.handle_debug_command(db, state, args)
        other = "npc_unwear " + json.dumps({"npc_id": "OTHER_SESSION_NPC", "item_id": "COAT"})
        assert "does not belong" in await DebugEngine.handle_debug_command(db, state, other)
        assert state.entity_states == original
