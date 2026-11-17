"""Source changes retain independent command and narration facts on the same actor."""

from copy import deepcopy
from types import SimpleNamespace

import pytest

from backend.engine.scene_staging.provenance import remap, retract, stamp
from backend.engine.scene_staging.shared import apply_extraction
from backend.engine.scene_staging.state import KEY, project
from tests.test_scene_command_reconciliation import TEXT, body, fixture


def mixed_sources():
    host, rows, cast = fixture()
    apply_extraction(
        host,
        TEXT,
        cast,
        rows,
        body(
            [
                {
                    "entity_id": "npc",
                    "placement": {
                        "relation": "near",
                        "target_kind": "character",
                        "target": "other",
                    },
                    "evidence": "NPC crawls near Other.",
                }
            ]
        ),
    )
    stamp(host.state, SimpleNamespace(id="reply", revision_id="reply-revision", content=TEXT))
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
    assert state.entity_states[KEY]["actors"]["npc"]["command"]["source_message_id"] == (
        "input" if operation == "regenerate" else "copied-input"
    )
    assert not state.entity_states[KEY].get("explicit")
    assert original[KEY]["actors"]["npc"]["placement"]["source_message_id"] == "reply"


@pytest.mark.parametrize("operation", ["input_edit", "partial_history_copy"])
def test_missing_command_input_preserves_independently_sourced_narration(operation):
    state, cast = mixed_sources()
    if operation == "input_edit":
        retract(state, "input")
    else:
        state.entity_states = remap(state.entity_states, {"reply": "copied-reply"})
    assert project(state, cast)["npc"] == {
        "placement": {"relation": "near", "target_kind": "character", "target": "other"}
    }
    assert "command" not in state.entity_states[KEY]["actors"]["npc"]
    assert state.entity_states[KEY]["actors"]["npc"]["placement"]["source_message_id"] == (
        "reply" if operation == "input_edit" else "copied-reply"
    )
