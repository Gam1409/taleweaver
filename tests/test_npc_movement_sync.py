"""Movement synchronization preserves session state and opens generated places."""

from types import SimpleNamespace

import pytest

from backend.engine.debug_engine import DebugEngine
from backend.engine.dynamic_locations.schema import KEY
from backend.engine.npc_movement import allowed_scenes
from backend.engine.visual_novel.story_director import _movable
from backend.models.world_entity import WorldEntity
from tests.test_npc_movement_and_notes import _seed_test_context


@pytest.mark.asyncio
async def test_bulk_movement_refreshes_template_restrictions(setup_test_db):
    from tests.conftest import TestSessionLocal

    async with TestSessionLocal() as db:
        _, adventure, _, state = await _seed_test_context(db)
        state.template_id = adventure.id
        db.add(
            WorldEntity(
                id="NPC_STAT",
                template_id=adventure.id,
                session_id=None,
                entity_type="NPC",
                name="Guard",
                description="Guard",
                current_scene_id="SCENE_A",
                allowed_scenes=["SCENE_C"],
            )
        )
        state.entity_states = {"NPC_STAT": {"allowed_scenes": ["SCENE_A"], "notes": "Keep me"}}
        await db.commit()
        result = await DebugEngine.handle_debug_command(db, state, "moveable all true")
        assert "Scene restrictions refreshed from the adventure for 1 NPCs" in result
        await db.refresh(state)
        assert state.entity_states["NPC_STAT"] == {
            "moveable": True,
            "allowed_scenes": ["SCENE_C"],
            "notes": "Keep me",
        }
        assert state.entity_states["NPC_MOV"]["moveable"] is True
        assert "allowed_scenes" not in state.entity_states["NPC_MOV"]
        await DebugEngine.handle_debug_command(db, state, "moveable all false")
        assert state.entity_states["NPC_STAT"]["moveable"] is False
        assert state.entity_states["NPC_STAT"]["allowed_scenes"] == ["SCENE_C"]


def test_generated_places_extend_restrictions_without_enabling_stationary_npcs():
    npc = SimpleNamespace(id="NPC", moveable=True, movement_type="MOVABLE", allowed_scenes=["A"])
    state = SimpleNamespace(entity_states={KEY: {"places": {"GENERATED": {}}}})
    assert allowed_scenes(npc, state.entity_states) == ["A", "GENERATED"]
    assert _movable(state, npc, "GENERATED")
    assert not _movable(state, npc, "B")
    state.entity_states["NPC"] = {"moveable": False}
    assert not _movable(state, npc, "GENERATED")
    state.entity_states["NPC"] = {"allowed_scenes": []}
    assert allowed_scenes(npc, state.entity_states) == []
    assert _movable(state, npc, "B")


@pytest.mark.asyncio
async def test_generated_destination_passes_guardrails_and_living_world(setup_test_db):
    from sqlalchemy import select

    from backend.api.routes.adventures.guardrails.world_rules import WorldRulesMixin
    from backend.engine.living_world.decision_context import destinations
    from backend.engine.living_world.rules import move
    from backend.engine.living_world.schema import Event
    from backend.engine.rule_engine import EntityMovement
    from backend.models.world_entity import WorldExit, WorldScene
    from tests.conftest import TestSessionLocal

    async with TestSessionLocal() as db:
        user, adventure, avatar, state = await _seed_test_context(db)
        state.entity_states = {KEY: {"places": {"GENERATED": {}}}}
        target = WorldScene(
            id="GENERATED",
            session_id=state.session_id,
            label="Generated",
            description="Generated place",
        )
        edge = WorldExit(
            id="DYNAMIC_EXIT",
            session_id=state.session_id,
            from_scene_id="SCENE_A",
            to_scene_id="GENERATED",
            label="Door",
            is_locked=False,
        )
        db.add_all([target, edge])
        await db.flush()
        npc = await db.scalar(
            select(WorldEntity).where(
                WorldEntity.session_id == state.session_id, WorldEntity.id == "NPC_MOV"
            )
        )
        origin = await db.scalar(
            select(WorldScene).where(
                WorldScene.session_id == state.session_id, WorldScene.id == "SCENE_A"
            )
        )
        manager = WorldRulesMixin()
        manager.state, manager.adventure, manager.avatar = state, adventure, avatar
        movement = EntityMovement(entity_id=npc.id, to_scene_id="GENERATED")
        assert manager._npc_move_violation(npc, movement) is None
        assert "GENERATED" in await destinations(db, state, npc, origin)
        event = Event(
            event_id="test-move", kind="MOVE", actor=npc.id, destination="GENERATED", due=1
        )
        await move(db, state, event, npc)
        assert state.entity_states[npc.id]["current_scene_id"] == "GENERATED"
        state.entity_states = {KEY: {"places": {"GENERATED": {}}}}
        edge.is_locked = True
        assert "GENERATED" not in await destinations(db, state, npc, origin)
        blocked = Event(
            event_id="blocked", kind="MOVE", actor=npc.id, destination="GENERATED", due=2
        )
        await move(db, state, blocked, npc)
        assert blocked.status == "CANCELLED"
        assert npc.id not in state.entity_states


def test_prompt_includes_generated_places_without_changing_authored_list():
    from backend.api.routes.adventures.turn_context_helpers import apply_entity_overrides

    npc = WorldEntity(id="NPC", entity_type="NPC", allowed_scenes=["A"])
    apply_entity_overrides([npc], {KEY: {"places": {"GENERATED": {}}}})
    assert npc.session_allowed_scenes == ["A", "GENERATED"]
    assert npc.allowed_scenes == ["A"]
