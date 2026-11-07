"""Manual player relocation is session-scoped and never moves NPCs implicitly."""

from copy import deepcopy

import pytest
from sqlalchemy import select

from backend.engine.debug_engine import DebugEngine
from backend.engine.gameplay.manager import GameTurnManager
from backend.models.world_entity import WorldScene
from tests.conftest import TestSessionLocal
from tests.test_vn_turn_integration import final_payload, seed_vn


async def test_debug_player_move_round_trips_with_scene_and_entities_without_model(monkeypatch):
    async with TestSessionLocal() as db:
        user, avatar, state, _ = await seed_vn(db)
        state.is_debug_enabled = True
        state.entity_states = {**state.entity_states, "__scene_staging__": {"old": "pose"}}
        db.add(
            WorldScene(
                id="RESEARCH_LAB",
                session_id="session-1",
                label="Лаборатория",
                description="Equipment.",
            )
        )
        await db.commit()
        inventory, clock = deepcopy(avatar.inventory), state.in_game_time
        events = [
            event
            async for event in GameTurnManager(db, "session-1", user).process_turn(
                '/debug move_player "RESEARCH_LAB"'
            )
        ]
        final = final_payload(events)
        assert final["scene_id"] == "RESEARCH_LAB"
        assert final["sheet"]["scene_id"] == "RESEARCH_LAB"
        await db.refresh(state)
        assert state.current_scene_id == "RESEARCH_LAB"
        assert "RESEARCH_LAB" in state.discovered_scenes
        assert "__scene_staging__" not in state.entity_states
        assert state.in_game_time == clock and avatar.inventory == inventory
        assert not final["entities"]  # The NPCs were deliberately left in their own location.
        assert (
            "LINA" not in state.entity_states
            or state.entity_states["LINA"].get("current_scene_id", "START") == "START"
        )


@pytest.mark.parametrize(
    "command,enabled",
    [("move_player START", False), ("move_player FOREIGN", True), ('move_player "broken', True)],
)
async def test_invalid_or_disabled_manual_move_preserves_current_state(command, enabled):
    async with TestSessionLocal() as db:
        user, avatar, state, _ = await seed_vn(db)
        state.is_debug_enabled = enabled
        before = deepcopy(state.entity_states)
        result = await DebugEngine.handle_debug_command(
            db, state, command, user=user, avatar=avatar
        )
        assert result.startswith("DEBUG ERROR:")
        assert state.current_scene_id == "START" and state.entity_states == before


async def test_same_name_in_another_session_cannot_be_used_as_a_destination():
    async with TestSessionLocal() as db:
        _, _, state, _ = await seed_vn(db)
        state.is_debug_enabled = True
        assert await db.scalar(select(WorldScene).where(WorldScene.session_id == "session-1"))
        result = await DebugEngine.handle_debug_command(
            db, state, 'move_player "FOREIGN_SESSION_ID"'
        )
        assert result.startswith("DEBUG ERROR:")
        assert state.current_scene_id == "START"
