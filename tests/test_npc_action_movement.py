"""NPC movement commands use current routes without moving the player or advancing time."""

import json
from hashlib import sha256
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from backend.engine.chpm.observable_state import capture as capture_views
from backend.engine.chpm.schema import Observation
from backend.engine.gameplay.manager import GameTurnManager
from backend.engine.gameplay.turn_prompt_layout import build_narration_turn_block
from backend.engine.npc_actions.contracts import Move, Take
from backend.engine.npc_actions.preparation import capture as capture_actions
from backend.engine.npc_actions.publication import publish
from backend.engine.npc_presence import movement_resolution
from backend.engine.rule_engine import EntityMovement, GameEvent
from backend.models.chat import ChatMessage
from backend.models.session_state import SessionState
from backend.models.world_entity import WorldEntity, WorldExit, WorldScene
from tests.conftest import TestSessionLocal
from tests.test_vn_turn_integration import seed_vn


async def movement_fixture(db, *, reverse=False, bidirectional=False, allowed=None):
    user, avatar, state, _ = await seed_vn(db)
    actor = await db.scalar(
        select(WorldEntity).where(
            WorldEntity.session_id == state.session_id, WorldEntity.id == "LINA"
        )
    )
    actor.moveable = True
    actor.allowed_scenes = allowed
    actor.spatial_position = "beside the shelves"
    state.in_game_time = 23
    db.add_all(
        [
            WorldScene(
                id="ANNEX", session_id=state.session_id, label="Annex", description="A quiet annex."
            ),
            WorldScene(
                id="VAULT",
                session_id=state.session_id,
                label="Vault",
                description="A distant vault.",
            ),
        ]
    )
    edge = WorldExit(
        session_id=state.session_id,
        from_scene_id="ANNEX" if reverse else "START",
        to_scene_id="START" if reverse else "ANNEX",
        label="Annex door",
        exit_type="bidirectional" if bidirectional else "one_way",
        is_locked=False,
    )
    message = ChatMessage(
        session_id=state.session_id,
        role="user",
        content="The visitor considers leaving through the annex door.",
        scene_id="START",
    )
    db.add_all([edge, message])
    await db.commit()
    manager = GameTurnManager(db, state.session_id, user, state=state, avatar=avatar)
    assert await manager.initialize()
    manager._vn_player_message_id = message.id
    observed = Observation(
        session_id=state.session_id,
        message_id=message.id,
        revision_id=message.revision_id,
        content_hash=sha256(message.content.encode()).hexdigest(),
        sequence=0,
        scene_id="START",
        minute=23,
        player_request=message.content,
    )
    views = await capture_views(manager, ["LINA"], observed)
    drafts = await capture_actions(manager, views, observed)
    return manager, actor, edge, observed, drafts["LINA"]


@pytest.mark.parametrize("reverse,bidirectional", [(False, False), (True, True)])
async def test_permitted_departure_persists_once_without_relocating_player_or_advancing_clock(
    reverse, bidirectional
):
    async with TestSessionLocal() as db:
        manager, _, _, _, draft = await movement_fixture(
            db, reverse=reverse, bidirectional=bidirectional
        )
        original_clock = manager.state.in_game_time
        original_scene = manager.state.current_scene_id
        assert (
            draft.execute(Move(tool="move_to", destination_scene_id="ANNEX"))["status"] == "staged"
        )
        assert (
            draft.execute(Take(tool="take_item", item_id="HIDDEN_RING"))["status"]
            == "scene_frame_ended"
        )
        draft.approved = True
        results = await publish(manager, draft)
        assert results[0]["status"] == "applied"
        assert results[0]["effect"]["destination_scene_id"] == "ANNEX"
        first_count = await db.scalar(select(func.count()).select_from(ChatMessage))
        assert await publish(manager, draft) == results
        assert await db.scalar(select(func.count()).select_from(ChatMessage)) == first_count
        await db.commit()
        state_id = manager.state.id
    async with TestSessionLocal() as db:
        saved = await db.get(SessionState, state_id)
        assert saved.current_scene_id == original_scene == "START"
        assert saved.in_game_time == original_clock == 23
        assert saved.entity_states["LINA"]["current_scene_id"] == "ANNEX"
        assert saved.entity_states["LINA"]["presence"] == "present"
        assert saved.entity_states["LINA"]["spatial_position"] is None


@pytest.mark.parametrize("lock_source", ["row", "override"])
async def test_an_exit_locked_after_preview_blocks_departure_without_mutating_actor(lock_source):
    async with TestSessionLocal() as db:
        manager, _, edge, _, draft = await movement_fixture(db)
        assert (
            draft.execute(Move(tool="move_to", destination_scene_id="ANNEX"))["status"] == "staged"
        )
        if lock_source == "row":
            edge.is_locked = True
        else:
            manager.state.exit_states = {edge.id: {"is_locked": True}}
        draft.approved = True
        result = await publish(manager, draft)
        assert result[0]["status"] == "blocked"
        assert manager.state.current_scene_id == "START" and manager.state.in_game_time == 23
        assert (
            manager.state.entity_states.get("LINA", {}).get("current_scene_id", "START") == "START"
        )
        assert not await db.scalar(select(ChatMessage).where(ChatMessage.role == "system"))


@pytest.mark.parametrize(
    "restriction", [{"moveable": False}, {"allowed_scenes": ["VAULT"]}, {"presence": "absent"}]
)
async def test_current_mobility_and_room_restrictions_are_rechecked_before_publication(restriction):
    async with TestSessionLocal() as db:
        manager, _, _, _, draft = await movement_fixture(db)
        assert (
            draft.execute(Move(tool="move_to", destination_scene_id="ANNEX"))["status"] == "staged"
        )
        manager.state.entity_states = {**manager.state.entity_states, "LINA": restriction}
        draft.approved = True
        assert (await publish(manager, draft))[0]["status"] == "blocked"
        assert manager.state.current_scene_id == "START" and manager.state.in_game_time == 23
        assert manager.state.entity_states["LINA"] == restriction


@pytest.mark.parametrize("options", [{"reverse": True}, {"allowed": ["VAULT"]}])
async def test_reverse_one_way_and_forbidden_destinations_never_stage_a_departure(options):
    async with TestSessionLocal() as db:
        manager, _, _, _, draft = await movement_fixture(db, **options)
        assert (
            draft.execute(Move(tool="move_to", destination_scene_id="ANNEX"))["status"] == "blocked"
        )
        assert draft.requests == []
        assert manager.state.current_scene_id == "START"


async def test_narrator_sees_one_final_cast_after_preliminary_and_command_departures():
    async with TestSessionLocal() as db:
        manager, _, _, _, draft = await movement_fixture(db)
        first = WorldEntity(
            id="VISITOR",
            name="Visitor",
            entity_type="NPC",
            description="A visitor.",
            current_scene_id="START",
            session_id=manager.game_id,
        )
        db.add(first)
        manager.state.entity_states = {
            **manager.state.entity_states,
            first.id: {"current_scene_id": "ANNEX", "remembered": True},
        }
        await db.flush()
        builder = manager._llm_context_builder
        world = await builder._load_world()
        preliminary = GameEvent(
            moved_entities=[EntityMovement(entity_id=first.id, to_scene_id="ANNEX")]
        )
        movement_note = movement_resolution(world.all_entities, manager.state, preliminary)

        assert (
            draft.execute(Move(tool="move_to", destination_scene_id="ANNEX"))["status"] == "staged"
        )
        draft.approved = True
        assert (await publish(manager, draft))[0]["status"] == "applied"
        context = SimpleNamespace(global_unlock_rules_prompt_block="", narration_addendum="")
        await builder.refresh_narration_state(context)

        prompt = build_narration_turn_block(
            context.narration_state_block, "", "{}", [], reminders=(movement_note,)
        )
        header = "CURRENT NPC PRESENCE (authoritative, not historical memory):"
        casts = [
            json.JSONDecoder().raw_decode(part.lstrip())[0] for part in prompt.split(header)[1:]
        ]
        assert casts == [[]]
        assert (
            '"npc_id": "VISITOR"' in movement_note
            and '"current_scene_id": "ANNEX"' in movement_note
        )
