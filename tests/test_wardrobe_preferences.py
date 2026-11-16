"""Explicit debug preferences change session facts, never infer age or edit templates."""

import json
from copy import deepcopy

import pytest
from sqlalchemy import select

from backend.engine.clothing.recovery_context import KEY, recovery_context
from backend.engine.clothing.wardrobe_preferences import read_preferences
from backend.engine.debug_engine import DebugEngine
from backend.engine.debug_npc_tools import wardrobe_info
from backend.models.adventure_template import AdventureTemplate
from backend.models.world_entity import WorldEntity
from tests.conftest import TestSessionLocal
from tests.test_vn_turn_integration import seed_vn


def command(expected, settings, npc_id="LINA"):
    return "wardrobe_settings " + json.dumps(
        {"npc_id": npc_id, "expected": expected, "settings": settings}
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("age", [None, 30])
async def test_save_round_trips_session_setting_and_age_without_changing_template_or_outfit(age):
    async with TestSessionLocal() as db:
        _, avatar, state, _ = await seed_vn(db)
        adventure = await db.get(AdventureTemplate, state.template_id)
        npc = await db.scalar(select(WorldEntity).where(WorldEntity.id == "LINA"))
        npc.age_years = 40
        npc.visual_profile = {"appearance": {"age_years": 40, "hair": "black"}, "worn": []}
        state.is_debug_enabled = True
        original = {
            "clothing_settings": {"detailed": False},
            "mature_content": {"enabled": True, "level": "medium"},
            "title": "Unchanged story",
        }
        state.entity_states = {
            "__manifest_snapshot__": {"original_manifest": deepcopy(original)},
            KEY: {"token": "obsolete"},
            "LINA": {"visual_profile": deepcopy(npc.visual_profile), "spatial_position": "chair"},
        }
        template_before = deepcopy(adventure.original_manifest)
        inventory_before = deepcopy(npc.inventory)
        expected = read_preferences(npc, state.entity_states)
        settings = {"detailed": True, "age_years": age}
        result = await DebugEngine.handle_debug_command(db, state, command(expected, settings))
        assert result.startswith("DEBUG: Saved"), result
        await db.commit()
        await db.refresh(state)
        await db.refresh(npc)
        saved = state.entity_states["__manifest_snapshot__"]["original_manifest"]
        assert saved == {**original, "clothing_settings": {"detailed": True}}
        assert adventure.original_manifest == template_before
        assert npc.inventory == inventory_before
        assert npc.age_years == age and npc.visual_profile["appearance"]["age_years"] == age
        assert state.entity_states["LINA"]["visual_profile"]["appearance"]["age_years"] == age
        assert state.entity_states["LINA"]["spatial_position"] == "chair"
        assert KEY not in state.entity_states
        assert wardrobe_info(npc, [npc], state.entity_states)["preferences"] == settings
        assert (await recovery_context(db, state, avatar, "LINA"))["actor"].get("age_years") == age
        stale = await DebugEngine.handle_debug_command(db, state, command(expected, settings))
        assert "changed" in stale


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure",
    [
        "disabled",
        "missing_manifest",
        "unknown_npc",
        "stale",
        "age_string",
        "age_bool",
        "detail_string",
    ],
)
async def test_rejected_setting_changes_preserve_every_fact(failure):
    async with TestSessionLocal() as db:
        _, _, state, _ = await seed_vn(db)
        npc = await db.scalar(select(WorldEntity).where(WorldEntity.id == "LINA"))
        state.is_debug_enabled = failure != "disabled"
        state.entity_states = {KEY: {"token": "keep"}}
        expected = read_preferences(npc, state.entity_states)
        settings = {"detailed": True, "age_years": 30}
        identifier = "OTHER_SESSION_NPC" if failure == "unknown_npc" else "LINA"
        if failure == "stale":
            expected["detailed"] = True
        if failure == "age_string":
            settings["age_years"] = "30"
        if failure == "age_bool":
            settings["age_years"] = True
        if failure == "detail_string":
            settings["detailed"] = "true"
        before = deepcopy(state.entity_states)
        age_before = npc.age_years
        result = await DebugEngine.handle_debug_command(
            db, state, command(expected, settings, identifier)
        )
        assert result.startswith("DEBUG ERROR:"), result
        assert state.entity_states == before and npc.age_years == age_before
