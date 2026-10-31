"""Scene orientation is replaceable advice, not an event ledger or an initiative gate."""

from types import SimpleNamespace

import pytest

from backend.engine.visual_novel.intent import VNProgressionIntent
from backend.engine.visual_novel.scene_focus import focus_context, focus_reminder, stage_focus
from backend.engine.visual_novel.story_director import STATE_KEY, record_direction


def manager_with_focus():
    return SimpleNamespace(
        state=SimpleNamespace(current_scene_id="HALL", entity_states={"kept": {"value": 1}}),
        _vn_story_beat=None,
    )


def proposal_with_focus(**overrides):
    return VNProgressionIntent.model_validate(
        {
            "scene_focus": {
                "current_goal": "Find the missing letter",
                "open_question": "Who moved it?",
                "last_observed_change": "Lina has finished her explanation",
                "evidence": "Lina finishes explaining.",
                **overrides,
            }
        }
    )


def test_focus_can_be_stored_without_a_story_beat_and_does_not_become_an_event():
    manager = manager_with_focus()
    proposal = proposal_with_focus()
    stage_focus(manager, proposal, [{"role": "assistant", "content": "Lina finishes explaining."}])
    assert "SCENE ORIENTATION" in focus_reminder(manager)
    assert STATE_KEY not in manager.state.entity_states
    record_direction(manager, "new-reply", completed=True)
    assert (
        focus_context(manager.state)["last_observed_change"] == "Lina has finished her explanation"
    )
    assert manager.state.entity_states[STATE_KEY]["focus"]["message_id"] == "new-reply"
    assert manager.state.entity_states["kept"] == {"value": 1}
    assert not proposal.remember_notes and not proposal.new_world_memories


@pytest.mark.parametrize("source", ["user", "old_assistant", "none"])
def test_new_attempts_old_quotes_and_unobserved_plans_do_not_support_observations(source):
    manager = manager_with_focus()
    history = [
        {
            "role": "assistant" if source == "old_assistant" else "user",
            "content": "Lina finishes explaining.",
        }
    ]
    if source != "user":
        history.append({"role": "assistant", "content": "Lina is still speaking."})
    stage_focus(manager, proposal_with_focus(), [] if source == "none" else history)
    record_direction(manager, "reply", completed=True)
    focus = focus_context(manager.state)
    assert focus["current_goal"] == "Find the missing letter"
    assert focus["last_observed_change"] == focus["evidence"] == ""


def test_observation_matches_the_same_voice_cleaned_context_the_planner_received():
    manager = manager_with_focus()
    stage_focus(
        manager,
        proposal_with_focus(),
        [{"role": "assistant", "content": "Lina <sigh>finishes explaining."}],
    )
    record_direction(manager, "reply", completed=True)
    assert focus_context(manager.state)["evidence"] == "Lina finishes explaining."


def test_focus_is_replaced_over_many_turns_and_not_added_to_planning_history():
    manager = manager_with_focus()
    for number in range(20):
        stage_focus(manager, proposal_with_focus(current_goal=f"Goal {number}"), [])
        record_direction(manager, str(number), completed=True)
    stored = manager.state.entity_states[STATE_KEY]
    assert set(stored) == {"focus"}
    assert stored["focus"]["message_id"] == "19"
    assert focus_context(manager.state)["current_goal"] == "Goal 19"


def test_incomplete_turn_does_not_replace_previous_focus():
    manager = manager_with_focus()
    stage_focus(manager, proposal_with_focus(), [])
    record_direction(manager, "first", completed=True)
    stage_focus(manager, proposal_with_focus(current_goal="A new goal"), [])
    record_direction(manager, "incomplete", completed=False)
    assert focus_context(manager.state)["current_goal"] == "Find the missing letter"


def test_scene_change_discards_previous_scene_focus_and_does_not_revive_it_on_return():
    manager = manager_with_focus()
    stage_focus(manager, proposal_with_focus(), [])
    record_direction(manager, "first", completed=True)
    manager.state.current_scene_id = "ROOM"
    assert focus_context(manager.state) == {}
    assert focus_reminder(manager) == ""
    record_direction(manager, "moved", completed=True)
    manager.state.current_scene_id = "HALL"
    assert focus_context(manager.state) == {}


def test_missing_focus_clears_stale_orientation_without_deleting_attempted_directions():
    manager = manager_with_focus()
    manager.state.entity_states[STATE_KEY] = {
        "version": 1,
        "recent": [],
        "focus": {"scene_id": "HALL"},
    }
    stage_focus(manager, VNProgressionIntent(), [])
    record_direction(manager, "reply", completed=True)
    assert manager.state.entity_states[STATE_KEY] == {"version": 1, "recent": []}


def test_malformed_focus_does_not_abort_valid_continuity():
    proposal = VNProgressionIntent.model_validate(
        {"scene_focus": {"current_goal": ["invalid"]}, "extra_time_minutes": 2}
    )
    assert proposal.scene_focus is None
    assert proposal.extra_time_minutes == 2
