"""Source changes retain independent command and narration facts on the same actor."""

from copy import deepcopy
from types import SimpleNamespace

import pytest

from backend.engine.scene_staging.provenance import remap, retract, stamp
from backend.engine.scene_staging.shared import apply_extraction
from backend.engine.scene_staging.state import KEY, project
from tests.npc_control_support import bind_turn
from tests.scene_command_sources import (
    MOVE_EVIDENCE,
    MOVE_INPUT,
    MOVE_TEXT,
    bind_player_source,
    external_change,
    player_authority,
)
from tests.test_scene_command_reconciliation import body, fixture


def mixed_sources():
    host, rows, cast = fixture()
    original_pose = deepcopy(host.state.entity_states[KEY]["actors"]["npc"]["posture"])
    # A later external cause must not depend on the original command's input.
    bind_player_source(host, MOVE_INPUT, input_id="external-input")
    host._chpm_turn.input_id = "external-input"
    host._chpm_turn.action_outcomes = {"npc": []}
    bind_turn(host, host._chpm_turn)
    apply_extraction(
        host,
        MOVE_TEXT,
        cast,
        rows,
        body(
            [
                external_change(
                    host,
                    MOVE_TEXT,
                    evidence=MOVE_EVIDENCE,
                    placement={
                        "relation": "near",
                        "target_kind": "character",
                        "target": "other",
                    },
                )
            ]
        ),
        authority=player_authority(host),
    )
    stamp(host.state, SimpleNamespace(id="reply", revision_id="reply-revision", content=MOVE_TEXT))
    actor = host.state.entity_states[KEY]["actors"]["npc"]
    assert actor["posture"] == original_pose
    assert actor["placement"]["source_kind"] == "external_effect"
    assert actor["placement"]["source_message_id"] == "reply"
    assert actor["placement"]["cause"]["source_message_id"] == "external-input"
    assert host.state.entity_states[KEY]["rejected"] == 0
    return host.state, cast


@pytest.mark.parametrize("operation", ["regenerate", "partial_history_copy"])
def test_replacing_independent_prose_preserves_the_committed_command_pose(operation):
    state, cast = mixed_sources()
    original = deepcopy(state.entity_states)
    expected = deepcopy(original[KEY]["actors"]["npc"]["posture"])
    if operation == "regenerate":
        retract(state, "reply")
    else:
        state.entity_states = remap(state.entity_states, {"input": "copied-input"})
        expected["source_message_id"] = "copied-input"
    assert project(state, cast)["npc"] == {"posture": "on_all_fours"}
    assert state.entity_states[KEY]["actors"]["npc"]["posture"] == expected
    assert state.entity_states[KEY]["actors"]["npc"]["posture"]["source_kind"] == "command"
    assert "command" not in state.entity_states[KEY]["actors"]["npc"]
    assert not state.entity_states[KEY].get("explicit")
    assert original[KEY]["actors"]["npc"]["placement"]["source_message_id"] == "reply"


@pytest.mark.parametrize("operation", ["input_edit", "partial_history_copy"])
def test_missing_command_input_preserves_independently_sourced_narration(operation):
    state, cast = mixed_sources()
    if operation == "input_edit":
        retract(state, "input")
    else:
        state.entity_states = remap(
            state.entity_states,
            {"reply": "copied-reply", "external-input": "copied-external-input"},
        )
    assert project(state, cast)["npc"] == {
        "placement": {"relation": "near", "target_kind": "character", "target": "other"}
    }
    assert "command" not in state.entity_states[KEY]["actors"]["npc"]
    assert state.entity_states[KEY]["actors"]["npc"]["placement"]["source_message_id"] == (
        "reply" if operation == "input_edit" else "copied-reply"
    )
    assert state.entity_states[KEY]["actors"]["npc"]["placement"]["cause"]["source_message_id"] == (
        "external-input" if operation == "input_edit" else "copied-external-input"
    )


@pytest.mark.parametrize("operation", ["external_input_edit", "copy_without_external_input"])
def test_missing_external_cause_clears_its_placement_without_erasing_command_posture(operation):
    state, cast = mixed_sources()
    original = deepcopy(state.entity_states[KEY]["actors"]["npc"]["posture"])
    if operation == "external_input_edit":
        retract(state, "external-input")
    else:
        state.entity_states = remap(
            state.entity_states, {"input": "copied-input", "reply": "copied-reply"}
        )
        original["source_message_id"] = "copied-input"
    assert project(state, cast)["npc"] == {"posture": "on_all_fours"}
    assert state.entity_states[KEY]["actors"]["npc"]["posture"] == original


def test_full_source_copy_remaps_both_external_dependencies_without_changing_the_facts():
    state, cast = mixed_sources()
    original = deepcopy(project(state, cast))
    state.entity_states = remap(
        state.entity_states,
        {
            "input": "copied-input",
            "external-input": "copied-external-input",
            "reply": "copied-reply",
        },
    )
    assert project(state, cast) == original
    actor = state.entity_states[KEY]["actors"]["npc"]
    assert actor["posture"]["source_message_id"] == "copied-input"
    assert actor["posture"]["source_kind"] == "command"
    assert actor["placement"]["source_message_id"] == "copied-reply"
    assert actor["placement"]["cause"]["source_message_id"] == "copied-external-input"
