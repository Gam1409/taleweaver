"""Historical movement uses source-time command authority without executing new actions."""

from copy import deepcopy

import pytest

from backend.engine.chpm.kernel import digest
from backend.engine.chpm.recovery_contracts import RecoveryAudit
from backend.engine.gameplay.manager import GameTurnManager
from backend.engine.gameplay.turn_state_applier import TurnStateApplier
from backend.engine.rule_engine import GameEvent
from backend.engine.visual_novel import movement_recovery, movement_sources
from backend.engine.visual_novel.intent import VNProgressionIntent
from backend.models.chat import ChatMessage
from tests.conftest import TestSessionLocal
from tests.test_vn_movement_recovery import DEPARTURE, proof, recovery_state
from tests.test_vn_movement_recovery_sources import previous_reply


async def prepared(db, *, marker=("LINA",), mode="live", presence="present", destination="ANNEX"):
    user, _, state = await recovery_state(db, mode=mode)
    previous = await previous_reply(db)
    previous.npc_recovery = RecoveryAudit(
        content_hash=digest(previous.content),
        revision_id=previous.revision_id,
        scene_id=previous.scene_id,
        actors={"LINA": 0},
        command_controlled_actor_ids=list(marker) if marker is not None else None,
    ).model_dump()
    request = ChatMessage(
        session_id=state.session_id, role="user", content="I study the map.", scene_id="START"
    )
    db.add(request)
    await db.commit()
    manager = GameTurnManager(db, state.session_id, user)
    await manager.initialize()
    manager._vn_player_message_id = request.id
    await movement_sources.prepare(manager)
    body = (
        {
            "moved_entities": [
                {"entity_id": "LINA", "to_scene_id": destination, "movement_source": proof()}
            ]
        }
        if destination
        else {
            "updated_entities": [
                {"entity_id": "LINA", "presence": presence, "movement_source": proof()}
            ]
        }
    )
    manager._vn_movement_proposal = VNProgressionIntent.model_validate(body)
    event = GameEvent.model_validate(body)
    return manager, previous, event


@pytest.mark.parametrize("change", ["absent", "empty", "different_actor", "malformed", "cursor"])
async def test_source_snapshot_rejects_authority_changes_but_keeps_cursor_progress(change):
    async with TestSessionLocal() as db:
        manager, previous, _ = await prepared(db)
        captured = manager._vn_movement_sources["previous_narration"]
        changed = deepcopy(previous.npc_recovery)
        if change == "absent":
            changed.pop("command_controlled_actor_ids")
        elif change == "empty":
            changed["command_controlled_actor_ids"] = []
        elif change == "different_actor":
            changed["command_controlled_actor_ids"] = ["OTHER"]
        elif change == "malformed":
            changed["command_controlled_actor_ids"] = [None]
        else:
            changed["actors"]["LINA"] = 1
        previous.npc_recovery = changed
        await db.flush()
        assert captured.matches(previous, manager.game_id) is (change == "cursor")


async def test_source_snapshot_does_not_upgrade_a_legacy_source_during_inference():
    async with TestSessionLocal() as db:
        manager, previous, _ = await prepared(db, marker=None)
        captured = manager._vn_movement_sources["previous_narration"]
        previous.npc_recovery = {
            **previous.npc_recovery,
            "command_controlled_actor_ids": ["LINA"],
        }
        assert not captured.matches(previous, manager.game_id)


@pytest.mark.parametrize("destination,presence", [("START", "present"), (None, "present")])
async def test_controlled_source_allows_zero_delta_location_and_presence_echoes(
    destination, presence
):
    async with TestSessionLocal() as db:
        manager, _, event = await prepared(db, destination=destination, presence=presence)
        assert await movement_recovery.resolve_event(manager, event) == []
        assert event.moved_entities or event.updated_entities


@pytest.mark.parametrize("mode", ["live", "off"])
@pytest.mark.parametrize("marker", [None, ()])
async def test_unmarked_legacy_and_explicit_noncontrolled_sources_keep_existing_recovery(
    mode, marker
):
    async with TestSessionLocal() as db:
        manager, _, event = await prepared(db, marker=marker, mode=mode)
        assert await movement_recovery.resolve_event(manager, event) == []
        assert event.moved_entities[0].to_scene_id == "ANNEX"


async def test_legacy_recovery_without_entity_overrides_keeps_existing_owner_defaults():
    async with TestSessionLocal() as db:
        manager, _, event = await prepared(db, marker=None, mode="off")
        manager.state.entity_states = None
        assert await movement_recovery.resolve_event(manager, event) == []
        assert event.moved_entities[0].to_scene_id == "ANNEX"


@pytest.mark.parametrize("mode", ["live", "off"])
async def test_source_time_control_blocks_new_presence_even_after_controller_is_disabled(mode):
    async with TestSessionLocal() as db:
        manager, _, event = await prepared(db, mode=mode, destination=None, presence="absent")
        assert await movement_recovery.resolve_event(manager, event)
        assert event.updated_entities[0].presence is None


@pytest.mark.parametrize("operation", ["update", "move", "implicit_clear"])
async def test_controlled_history_cannot_change_a_local_position(operation):
    async with TestSessionLocal() as db:
        manager, _, _ = await prepared(db, destination=None)
        manager.state.entity_states = {
            **manager.state.entity_states,
            "LINA": {"spatial_position": "by the window"},
        }
        row = {"entity_id": "LINA", "movement_source": proof()}
        if operation == "update":
            body = {"updated_entities": [{**row, "spatial_position": "by the bench"}]}
        else:
            body = {"moved_entities": [{**row, "to_scene_id": "START"}]}
            if operation == "move":
                body["moved_entities"][0]["to_spatial_position"] = "by the bench"
        manager._vn_movement_proposal = VNProgressionIntent.model_validate(body)
        event = GameEvent.model_validate(body)
        await movement_recovery.resolve_event(manager, event)
        await TurnStateApplier(manager).apply_narrated_movement(event)
        assert manager.state.entity_states["LINA"]["spatial_position"] == "by the window"


@pytest.mark.parametrize("marker", [None, ("LINA",)])
@pytest.mark.parametrize("presence", ["present", "audible", "absent"])
async def test_exact_position_echo_is_allowed_without_inventing_a_blocked_result(marker, presence):
    async with TestSessionLocal() as db:
        manager, previous, _ = await prepared(db, marker=marker, destination=None)
        manager.state.entity_states = {
            **manager.state.entity_states,
            "LINA": {"spatial_position": "by the window", "presence": presence},
        }
        body = {
            "updated_entities": [
                {
                    "entity_id": "LINA",
                    "spatial_position": "by the window",
                    "movement_source": proof(),
                }
            ]
        }
        manager._vn_movement_proposal = VNProgressionIntent.model_validate(body)
        event = GameEvent.model_validate(body)
        assert await movement_recovery.resolve_event(manager, event) == []
        await TurnStateApplier(manager).apply_narrated_movement(event)
        assert manager.state.entity_states["LINA"]["spatial_position"] == "by the window"
        assert not previous.npc_recovery.get("movement_outcomes")


@pytest.mark.parametrize("source_kind", ["previous_narration", "current_player_action"])
async def test_unmarked_history_and_current_external_actions_keep_local_position_updates(
    source_kind,
):
    async with TestSessionLocal() as db:
        manager, _, _ = await prepared(db, marker=None, destination=None)
        manager.state.entity_states = {
            **manager.state.entity_states,
            "LINA": {"spatial_position": "by the window"},
        }
        source = proof()
        if source_kind == "current_player_action":
            request = await db.get(ChatMessage, manager._vn_player_message_id)
            request.content = "I push Lina toward the bench."
            await db.flush()
            await movement_sources.prepare(manager)
            source = proof(
                "current_player_action", basis="resolved_external_effect", passage="player:p0"
            )
        body = {
            "updated_entities": [
                {"entity_id": "LINA", "spatial_position": "by the bench", "movement_source": source}
            ]
        }
        manager._vn_movement_proposal = VNProgressionIntent.model_validate(body)
        event = GameEvent.model_validate(body)
        assert await movement_recovery.resolve_event(manager, event) == []
        await TurnStateApplier(manager).apply_narrated_movement(event)
        assert manager.state.entity_states["LINA"]["spatial_position"] == "by the bench"


@pytest.mark.parametrize("change", ["hash", "revision", "scene", "control"])
async def test_stale_source_or_marker_cannot_authorize_an_idempotent_echo(change):
    async with TestSessionLocal() as db:
        manager, previous, event = await prepared(db, destination="START")
        if change == "hash":
            previous.content = DEPARTURE + " Changed."
        elif change == "revision":
            previous.revision_id = "changed"
        elif change == "scene":
            previous.scene_id = "ANNEX"
        else:
            previous.npc_recovery = {**previous.npc_recovery, "command_controlled_actor_ids": []}
        await db.flush()
        assert await movement_recovery.resolve_event(manager, event)
        assert event.moved_entities == []
