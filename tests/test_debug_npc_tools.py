"""Debug corrections preserve session ownership, unrelated inventory and canonical clothing."""

import json
from copy import deepcopy

import pytest
from sqlalchemy import select

from backend.engine.debug_engine import DebugEngine
from backend.engine.debug_npc_tools import wardrobe_info
from backend.models.world_entity import WorldEntity, WorldScene
from tests.conftest import TestSessionLocal
from tests.test_vn_turn_integration import seed_vn


@pytest.mark.asyncio
async def test_manual_move_updates_session_presence_not_authored_npc_or_visibility():
    async with TestSessionLocal() as db:
        _, _, state, _ = await seed_vn(db)
        state.is_debug_enabled = True
        npc = await db.scalar(select(WorldEntity).where(WorldEntity.id == "LINA"))
        db.add(
            WorldScene(
                id="NEW PLACE",
                session_id=state.session_id,
                label="New place",
                description="A new room.",
            )
        )
        state.entity_states = {
            "LINA": {"is_hidden": True, "presence": "absent", "spatial_position": "chair"},
            "__scene_staging__": {"actors": {"LINA": {}}},
        }
        await db.flush()
        result = await DebugEngine.handle_debug_command(db, state, 'move_npc "LINA" "NEW PLACE"')
        assert result.startswith("DEBUG: Moved")
        await db.commit()
        await db.refresh(state)
        assert state.entity_states["LINA"]["current_scene_id"] == "NEW PLACE"
        assert state.entity_states["LINA"]["presence"] == "present"
        assert state.entity_states["LINA"]["spatial_position"] is None
        assert state.entity_states["LINA"]["is_hidden"] is True
        assert "__scene_staging__" not in state.entity_states
        assert npc.current_scene_id == "START"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "command", ["move_npc LINA UNKNOWN", "move_npc UNKNOWN START", 'move_npc "broken']
)
async def test_invalid_move_preserves_state(command):
    async with TestSessionLocal() as db:
        _, _, state, _ = await seed_vn(db)
        state.is_debug_enabled = True
        before = deepcopy(state.entity_states)
        result = await DebugEngine.handle_debug_command(db, state, command)
        assert result.startswith("DEBUG ERROR:") and state.entity_states == before


@pytest.mark.asyncio
@pytest.mark.parametrize("canonical", [False, True])
async def test_edit_clothing_round_trips_without_changing_unrelated_inventory(canonical):
    async with TestSessionLocal() as db:
        _, _, state, _ = await seed_vn(db)
        state.is_debug_enabled = True
        npc = await db.scalar(select(WorldEntity).where(WorldEntity.id == "LINA"))
        garment = {"layer": 1, "coverage": ["torso"]}
        shirt = {
            "id": "SHIRT",
            "name": "Old shirt",
            "clothing": garment,
            "wearable_slots": ["Chest"],
            "item_origin": {"source": "kept"},
        }
        npc.inventory = [*npc.inventory, shirt]
        npc.visual_profile = {"appearance": {"hair": "black"}, "worn": []}
        if canonical:
            db.add(
                WorldEntity(
                    id="SHIRT",
                    session_id=state.session_id,
                    entity_type="OBJECT",
                    name="Old shirt",
                    description="Old shirt.",
                    current_scene_id="START",
                    metadata_json={"clothing": garment},
                )
            )
        await db.flush()
        edit = {
            "npc_id": "LINA",
            "item_id": "SHIRT",
            "name": "Blue shirt",
            "description": "A blue cotton shirt.",
            "clothing": {"layer": 2, "coverage": ["torso", "arms"]},
            "worn": True,
        }
        result = await DebugEngine.handle_debug_command(
            db, state, "npc_clothing " + json.dumps(edit)
        )
        assert result.startswith("DEBUG: Updated"), result
        await db.commit()
        await db.refresh(state)
        saved = state.entity_states["LINA"]
        assert saved["inventory"][0] == {"id": "HIDDEN_RING", "name": "Hidden ring"}
        assert saved["inventory"][1]["item_origin"] == shirt["item_origin"]
        assert saved["inventory"][1]["wearable_slots"] == ["Chest"]
        assert saved["visual_profile"]["appearance"]["hair"] == "black"
        entities = list(
            await db.scalars(select(WorldEntity).where(WorldEntity.session_id == state.session_id))
        )
        info = wardrobe_info(npc, entities, state.entity_states)
        assert info["items"][0]["name"] == "Blue shirt"
        assert info["items"][0]["clothing"]["layer"] == 2
        assert info["items"][0]["worn"] is True
        assert npc.inventory[1]["name"] == "Old shirt"
        edit["worn"] = False
        result = await DebugEngine.handle_debug_command(
            db, state, "npc_clothing " + json.dumps(edit)
        )
        assert result.startswith("DEBUG: Updated")
        assert state.entity_states["LINA"]["visual_profile"]["worn"] == []
        before = deepcopy(state.entity_states)
        edit["item_id"] = "NOT_OWNED"
        assert (
            await DebugEngine.handle_debug_command(db, state, "npc_clothing " + json.dumps(edit))
        ).startswith("DEBUG ERROR:")
        assert state.entity_states == before


@pytest.mark.asyncio
async def test_corrections_require_enabled_debug():
    async with TestSessionLocal() as db:
        _, _, state, _ = await seed_vn(db)
        state.is_debug_enabled = False
        for command in ("move_npc LINA START", "npc_clothing {}"):
            assert "Enable debug mode" in await DebugEngine.handle_debug_command(db, state, command)
