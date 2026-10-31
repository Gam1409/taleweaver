"""Autonomous initiative never supplies the player's action or bypasses continuity."""

from types import SimpleNamespace

import pytest

from backend.engine.rule_engine import GameEvent
from backend.engine.visual_novel.intent import VNProgressionIntent
from backend.engine.visual_novel.story_director import (
    STATE_KEY,
    direction_context,
    direction_reminder,
    recent_directions,
    record_direction,
    stage_direction,
)

ACTION = "You can go now; I want to examine the painting."


def setup_direction(*, phase="open", kind="departure", evidence=ACTION):
    state = SimpleNamespace(current_scene_id="HALL", entity_states={"kept": {"value": 1}})
    manager = SimpleNamespace(
        state=state, adventure=SimpleNamespace(plot="Find the missing letter.")
    )
    npc = SimpleNamespace(
        id="NPC",
        entity_type="NPC",
        current_scene_id="HALL",
        is_hidden=False,
        moveable=True,
        allowed_scenes=["ROOM"],
        character="Independent",
        goal="Fetch the letter",
    )
    exits = [{"from_scene_id": "HALL", "to_scene_id": "ROOM", "is_locked": False}]
    proposal = VNProgressionIntent.model_validate(
        {
            "scene_rhythm": {"phase": phase, "evidence": evidence},
            "story_beat": {
                "npc_id": "NPC",
                "kind": kind,
                "purpose": "Fetch the letter",
                "action": "Walk to the room alone"
                if kind == "departure"
                else "Explain why the letter matters",
                "destination_id": "ROOM" if kind == "departure" else None,
            },
        }
    )
    return manager, npc, exits, proposal, GameEvent()


def test_departure_adds_only_npc_movement_and_leaves_player_inventory_and_clock_alone():
    manager, npc, exits, proposal, event = setup_direction()
    stage_direction(manager, proposal, event, [npc], exits)
    assert [(move.entity_id, move.to_scene_id) for move in event.moved_entities] == [
        ("NPC", "ROOM")
    ]
    assert event.new_scene_id is None
    assert not event.new_inventory_items and not event.extra_time_minutes
    assert "APPROVED NPC INITIATIVE" in direction_reminder(manager, event)
    assert STATE_KEY not in manager.state.entity_states  # No early/independent commit.


@pytest.mark.parametrize("phase", ["engaged", "settling", "open"])
@pytest.mark.parametrize("kind", ["departure", "dialogue"])
def test_scene_rhythm_does_not_veto_npc_initiative(phase, kind):
    manager, npc, exits, proposal, event = setup_direction(phase=phase, kind=kind)
    proposal.story_beat.relation = "transition"
    stage_direction(manager, proposal, event, [npc], exits)
    assert "APPROVED NPC INITIATIVE" in direction_reminder(manager, event)
    assert bool(event.moved_entities) == (kind == "departure")


def test_engaged_scene_allows_a_new_response_within_same_interaction():
    manager, npc, exits, proposal, event = setup_direction(phase="engaged", kind="dialogue")
    stage_direction(manager, proposal, event, [npc], exits)
    assert "Explain why the letter matters" in direction_reminder(manager, event)
    assert not event.moved_entities


@pytest.mark.parametrize(
    "failure",
    [
        "locked",
        "immobile",
        "restricted",
        "absent",
        "unknown",
        "player_moves",
        "other_origin",
    ],
)
def test_invalid_or_displaced_initiative_is_not_narrated(failure):
    manager, npc, exits, proposal, event = setup_direction()
    if failure == "locked":
        exits[0]["is_locked"] = True
    if failure == "immobile":
        npc.moveable = False
    if failure == "restricted":
        npc.allowed_scenes = ["ELSEWHERE"]
    if failure == "absent":
        manager.state.entity_states[npc.id] = {"presence": "absent"}
    if failure == "unknown":
        proposal.story_beat.npc_id = "invented"
    if failure == "player_moves":
        event.new_scene_id = "GARDEN"
    if failure == "other_origin":
        exits[0]["from_scene_id"] = "FOREST"
    stage_direction(manager, proposal, event, [npc], exits)
    assert not event.moved_entities and direction_reminder(manager, event) == ""


@pytest.mark.parametrize(
    "rhythm", [None, {"phase": "invalid"}, {"phase": "open", "evidence": "Not in history."}]
)
def test_missing_or_unmatched_rhythm_does_not_require_player_permission(rhythm):
    manager, npc, exits, proposal, event = setup_direction()
    proposal = VNProgressionIntent.model_validate({**proposal.model_dump(), "scene_rhythm": rhythm})
    stage_direction(manager, proposal, event, [npc], exits)
    assert event.moved_entities


def test_guardrail_rejection_cannot_leave_a_phantom_departure_in_narration_or_memory():
    manager, npc, exits, proposal, event = setup_direction()
    stage_direction(manager, proposal, event, [npc], exits)
    event.moved_entities = []
    assert direction_reminder(manager, event) == ""
    record_direction(manager, "reply", completed=True)
    assert STATE_KEY not in manager.state.entity_states


def test_attempted_directions_are_bounded_guidance_not_an_action_blacklist():
    manager, npc, exits, proposal, event = setup_direction(kind="dialogue")
    for number in range(6):
        proposal.story_beat.action = f"Explain reason {number}"
        stage_direction(manager, proposal, event, [npc], exits)
        record_direction(manager, str(number), completed=True)
    assert len(recent_directions(manager.state)) == 4
    assert manager.state.entity_states["kept"] == {"value": 1}
    assert direction_context(manager, [npc], exits)["premise"] == "Find the missing letter."
    assert "recent_attempted_beats_not_facts" in direction_context(manager, [npc], exits)
    proposal.story_beat.action = "  EXPLAIN reason 5!"
    stage_direction(manager, proposal, event, [npc], exits)
    assert "EXPLAIN reason 5!" in direction_reminder(manager, event)


def test_incomplete_narration_does_not_record_a_direction():
    manager, npc, exits, proposal, event = setup_direction(kind="dialogue")
    stage_direction(manager, proposal, event, [npc], exits)
    record_direction(manager, "reply", completed=False)
    assert STATE_KEY not in manager.state.entity_states


def test_malformed_optional_planning_does_not_abort_valid_continuity():
    proposal = VNProgressionIntent.model_validate(
        {
            "story_beat": {"npc_id": "NPC", "kind": "unrecognised"},
            "scene_rhythm": {"phase": "anything"},
            "extra_time_minutes": 2,
            "narrative_description": "The conversation takes two minutes.",
        }
    )
    assert proposal.story_beat is None
    assert "scene_rhythm" not in proposal.model_dump()
    assert proposal.extra_time_minutes == 2
