"""Narrated extraction cannot reverse applied pose fields or erase their real provenance."""

from copy import deepcopy
from types import SimpleNamespace

import pytest

from backend.engine.clothing.context import actor_records
from backend.engine.scene_staging.commands import CommandProof, apply_command
from backend.engine.scene_staging.runtime import reconcile_narration
from backend.engine.scene_staging.schema import Placement
from backend.engine.scene_staging.shared import _cast, apply_extraction, begin, consume
from backend.engine.scene_staging.state import KEY, project
from backend.engine.visual_novel.config import VnSettings, write_settings
from tests.npc_control_support import bind_turn
from tests.observable_state_support import world
from tests.test_item_command_state import change

TEXT = "NPC crawls near Other. Other sits."


def fixture(
    *, operation="set_pose", posture="on_all_fours", placement=None, effect=None, status="applied"
):
    host, rows = world()
    write_settings(host.state, VnSettings(scene_staging=True))
    host.state.entity_states, _ = change(host.state.entity_states)
    cast = _cast(host, actor_records(host, rows), rows)
    host._vn_player_message_id = "input"
    proof = CommandProof(
        command_id="command-1",
        actor_id="npc",
        scene_id="room",
        input_id="input",
        request_hash="a" * 64,
        operation=operation,
    )
    host.state.entity_states = apply_command(
        host.state.entity_states,
        scene_id="room",
        cast=cast,
        actor_id="npc",
        proof=proof,
        enabled=True,
        posture=posture,
        placement=placement,
    )
    host._chpm_turn = SimpleNamespace(
        input_id="input",
        initial=SimpleNamespace(settings=SimpleNamespace(mode="live", action_tools=True)),
        decisions={"npc": None},
        action_outcomes={
            "npc": [
                {
                    "tool": operation,
                    "status": status,
                    "effect": effect if effect is not None else {"posture": posture},
                }
            ]
        },
        simplified=False,
    )
    bind_turn(host, host._chpm_turn)
    return host, rows, cast


def body(changes):
    return {"changes": changes, "props": [], "explicit": []}


def test_handled_posture_keeps_command_source_while_independent_placement_and_other_actor_change():
    host, rows, cast = fixture()
    before = deepcopy(host.state.entity_states)
    apply_extraction(
        host,
        TEXT,
        cast,
        rows,
        body(
            [
                {
                    "entity_id": "npc",
                    "posture": "standing",
                    "placement": {
                        "relation": "near",
                        "target_kind": "character",
                        "target": "other",
                    },
                    "evidence": "NPC crawls near Other.",
                },
                {"entity_id": "other", "posture": "sitting", "evidence": "Other sits."},
            ]
        ),
    )
    shown = project(host.state, cast)
    assert shown["npc"] == {
        "posture": "on_all_fours",
        "placement": {"relation": "near", "target_kind": "character", "target": "other"},
    }
    assert shown["other"]["posture"] == "sitting"
    assert (
        host.state.entity_states[KEY]["actors"]["npc"]["posture"]
        == before[KEY]["actors"]["npc"]["posture"]
    )
    assert host.state.entity_states["__physical_conditions__"] == before["__physical_conditions__"]


def test_applied_approach_cannot_be_erased_by_a_clear_or_opposite_pose():
    placement = Placement(relation="near", target_kind="character", target="avatar")
    host, rows, cast = fixture(
        operation="approach",
        placement=placement,
        effect={"posture": "on_all_fours", "placement": placement.model_dump(), "mode": "crawl"},
    )
    before = deepcopy(project(host.state, cast)["npc"])
    apply_extraction(
        host,
        TEXT,
        cast,
        rows,
        body(
            [
                {
                    "entity_id": "npc",
                    "clear": True,
                    "posture": "standing",
                    "evidence": "NPC crawls near Other.",
                }
            ]
        ),
    )
    assert project(host.state, cast)["npc"] == before


def test_explicitly_cleared_posture_remains_unknown_after_a_reconstructed_old_pose():
    host, rows, cast = fixture(posture="unknown")
    apply_extraction(
        host,
        TEXT,
        cast,
        rows,
        body([{"entity_id": "npc", "posture": "standing", "evidence": "NPC crawls near Other."}]),
    )
    assert "posture" not in project(host.state, cast)["npc"]


def test_pose_owner_cleared_placement_cannot_be_reconstructed_from_the_old_relation():
    placement = Placement(relation="near", target_kind="character", target="avatar")
    host, rows, cast = fixture(
        operation="approach",
        placement=placement,
        effect={"posture": "on_all_fours", "placement": placement.model_dump()},
    )
    host.state.entity_states = apply_command(
        host.state.entity_states,
        scene_id="room",
        cast=cast,
        actor_id="npc",
        proof=CommandProof(
            command_id="command-2",
            actor_id="npc",
            scene_id="room",
            input_id="input",
            request_hash="b" * 64,
            operation="set_pose",
        ),
        enabled=True,
        posture="sitting",
    )
    host._chpm_turn.action_outcomes["npc"].append(
        {
            "tool": "set_pose",
            "status": "applied",
            "effect": {"posture": "sitting", "placement": None},
        }
    )
    bind_turn(host, host._chpm_turn)
    apply_extraction(
        host,
        TEXT,
        cast,
        rows,
        body(
            [
                {
                    "entity_id": "npc",
                    "placement": placement.model_dump(),
                    "evidence": "NPC crawls near Other.",
                }
            ]
        ),
    )
    assert project(host.state, cast)["npc"] == {"posture": "sitting"}


def test_clear_only_clears_the_independent_placement_when_posture_was_command_owned():
    host, rows, cast = fixture()
    host.state.entity_states[KEY]["actors"]["npc"]["placement"] = {
        "relation": "near",
        "target_kind": "character",
        "target": "avatar",
        "target_origin": "",
        "evidence": "Before.",
        "source_hash": "old",
    }
    apply_extraction(
        host,
        TEXT,
        cast,
        rows,
        body([{"entity_id": "npc", "clear": True, "evidence": "NPC crawls near Other."}]),
    )
    assert project(host.state, cast)["npc"] == {"posture": "on_all_fours"}


def test_receipts_from_another_input_do_not_freeze_current_narrated_pose():
    host, rows, cast = fixture()
    host._vn_player_message_id = "next-input"
    apply_extraction(
        host,
        TEXT,
        cast,
        rows,
        body([{"entity_id": "npc", "posture": "standing", "evidence": "NPC crawls near Other."}]),
    )
    assert project(host.state, cast)["npc"]["posture"] == "standing"


def test_missing_or_malformed_changes_do_not_unconfirm_the_fields_already_applied():
    host, rows, cast = fixture()
    apply_extraction(
        host,
        TEXT,
        cast,
        rows,
        body(
            [{"entity_id": "npc", "posture": "unsupported", "evidence": "NPC crawls near Other."}]
        ),
        unconfirmed_sections=frozenset({"changes"}),
    )
    assert project(host.state, cast)["npc"]["posture"] == "on_all_fours"


@pytest.mark.parametrize("status", ["blocked", "attempted", "stale"])
def test_a_non_applied_receipt_does_not_freeze_the_actors_pose(status):
    host, rows, cast = fixture(status=status)
    apply_extraction(
        host,
        TEXT,
        cast,
        rows,
        body([{"entity_id": "npc", "posture": "standing", "evidence": "NPC crawls near Other."}]),
    )
    assert project(host.state, cast)["npc"]["posture"] == "standing"


def test_shared_extractor_failure_preserves_applied_pose_instead_of_emptying_all_staging():
    host, _, cast = fixture()
    assert begin(host, TEXT)
    assert consume(host, TEXT, completed=True)
    assert project(host.state, cast)["npc"]["posture"] == "on_all_fours"


async def test_unavailable_standalone_narration_preserves_applied_pose_without_inference():
    host, _, cast = fixture()
    await reconcile_narration(host, "", completed=False)
    assert project(host.state, cast)["npc"]["posture"] == "on_all_fours"
