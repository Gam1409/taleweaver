"""Host pose commands preserve scene ownership and truthful input provenance."""

from copy import deepcopy
from types import SimpleNamespace

import pytest

from backend.engine.scene_staging.commands import CommandProof, apply_command
from backend.engine.scene_staging.provenance import remap, retract, stamp
from backend.engine.scene_staging.schema import Placement
from backend.engine.scene_staging.state import KEY, project
from tests.test_scene_staging import CAST, TEXT, extraction, reconcile, state


def proof(operation="set_pose", **changes):
    return CommandProof(
        command_id="command-1",
        actor_id="LINA",
        scene_id="START",
        input_id="input",
        input_revision="revision",
        request_hash="a" * 64,
        operation=operation,
        **changes,
    )


def changed(session, *, posture=None, placement=None, operation="set_pose", **changes):
    return apply_command(
        session.entity_states,
        scene_id="START",
        cast=CAST,
        actor_id="LINA",
        proof=proof(operation),
        enabled=True,
        posture=posture,
        placement=placement,
        **changes,
    )


def test_posture_command_uses_existing_state_and_never_fabricates_narration():
    session = state()
    session.entity_states[KEY] = reconcile(session, CAST, TEXT, extraction())
    before = deepcopy(session.entity_states)
    session.entity_states = changed(session, posture="on_all_fours")
    assert session.entity_states["LINA"] == before["LINA"]
    assert project(session, CAST)["LINA"] == {"posture": "on_all_fours"}
    fact = session.entity_states[KEY]["actors"]["LINA"]["posture"]
    assert fact["source_kind"] == "command" and fact["source_message_id"] == "input"
    assert fact["source_hash"] == "a" * 64 and "evidence" not in fact
    assert before[KEY]["actors"]["LINA"]["posture"]["value"] == "standing"


def test_local_approach_changes_only_its_actor_and_invalidates_obsolete_relations():
    session = state()
    session.entity_states[KEY] = reconcile(session, CAST, TEXT, extraction())
    hero_before = deepcopy(session.entity_states[KEY]["actors"]["hero"]["posture"])
    session.entity_states = changed(
        session,
        posture="on_all_fours",
        placement=Placement(relation="near", target_kind="character", target="hero"),
        operation="approach",
    )
    view = project(session, CAST)
    assert view["LINA"] == {
        "posture": "on_all_fours",
        "placement": {"relation": "near", "target_kind": "character", "target": "hero"},
    }
    assert session.current_scene_id == "START"
    assert session.entity_states[KEY]["actors"]["hero"]["posture"] == hero_before


def test_object_approach_uses_a_known_id_and_preserves_it_behind_the_display_label():
    session = state()
    session.entity_states = changed(
        session,
        placement=Placement(relation="near", target_kind="scene_object", target="BENCH"),
        operation="approach",
        scene_objects={"BENCH": "Oak bench"},
    )
    placement = project(session, CAST)["LINA"]["placement"]
    assert placement == {"relation": "near", "target_kind": "scene_object", "target": "Oak bench"}
    assert session.entity_states[KEY]["actors"]["LINA"]["placement"]["target_id"] == "BENCH"


@pytest.mark.parametrize(
    "placement,objects",
    [
        (Placement(relation="near", target_kind="character", target="ABSENT"), {}),
        (Placement(relation="near", target_kind="character", target="LINA"), {}),
        (
            Placement(relation="near", target_kind="scene_object", target="MISSING"),
            {"BENCH": "Oak bench"},
        ),
    ],
)
def test_unknown_or_self_targets_are_rejected_without_overwriting_previous_state(
    placement, objects
):
    session = state()
    before = deepcopy(session.entity_states)
    with pytest.raises(ValueError):
        changed(session, placement=placement, operation="approach", scene_objects=objects)
    assert session.entity_states == before


def test_disabled_staging_and_misbound_proofs_cannot_publish():
    session = state()
    before = deepcopy(session.entity_states)
    with pytest.raises(ValueError, match="disabled"):
        apply_command(
            session.entity_states,
            scene_id="START",
            cast=CAST,
            actor_id="LINA",
            proof=proof(),
            enabled=False,
            posture="standing",
        )
    with pytest.raises(ValueError, match="scope"):
        apply_command(
            session.entity_states,
            scene_id="START",
            cast=CAST,
            actor_id="hero",
            proof=proof(),
            enabled=True,
            posture="standing",
        )
    assert session.entity_states == before


def test_copy_and_source_edits_preserve_command_poses_only_with_their_real_input():
    session = state()
    session.entity_states = changed(session, posture="kneeling")
    copied = remap(session.entity_states, {"input": "copied-input"})
    assert copied[KEY]["actors"]["LINA"]["posture"]["source_message_id"] == "copied-input"
    assert (
        project(SimpleNamespace(current_scene_id="START", entity_states=copied), CAST)["LINA"][
            "posture"
        ]
        == "kneeling"
    )
    retract(session, "unrelated-narration")
    assert project(session, CAST)["LINA"]["posture"] == "kneeling"
    retract(session, "input")
    assert "LINA" not in project(session, CAST)
    missing = remap(copied, {})
    assert "LINA" not in project(
        SimpleNamespace(current_scene_id="START", entity_states=missing), CAST
    )


def test_narration_stamp_cannot_relabel_command_provenance():
    session = state()
    session.entity_states = changed(session, posture="kneeling")
    fact = deepcopy(session.entity_states[KEY]["actors"]["LINA"]["posture"])
    stamp(
        session,
        SimpleNamespace(id="narration", revision_id="new-revision", content="A normal narration."),
    )
    assert session.entity_states[KEY]["actors"]["LINA"]["posture"] == fact


def test_pose_change_invalidates_other_relations_to_the_actor_but_not_their_posture():
    session = state()
    session.entity_states[KEY] = reconcile(session, CAST, TEXT, extraction())
    session.entity_states[KEY]["actors"]["hero"]["placement"] = {
        "relation": "near",
        "target_kind": "character",
        "target": "LINA",
        "target_origin": "garden",
        "source_message_id": "previous",
    }
    session.entity_states = changed = apply_command(
        session.entity_states,
        scene_id="START",
        cast=CAST,
        actor_id="LINA",
        proof=proof(),
        enabled=True,
        posture="on_all_fours",
    )
    assert project(session, CAST)["LINA"] == {"posture": "on_all_fours"}
    assert project(session, CAST)["hero"] == {"posture": "sitting"}
    assert changed["LINA"]["inventory"] == ["COAT"]


def test_new_scene_command_does_not_republish_an_old_rooms_frame_or_activities():
    session = state()
    session.entity_states[KEY] = {
        "scene_id": "OLD_ROOM",
        "status": "ready",
        "actors": {},
        "source_message_id": "old-narration",
        "source_hash": "b" * 64,
        "explicit": [{"category": "undressing", "participants": ["ABSENT"]}],
    }
    session.entity_states = apply_command(
        session.entity_states,
        scene_id="START",
        cast=CAST,
        actor_id="LINA",
        proof=proof(),
        enabled=True,
        posture="standing",
    )
    assert session.entity_states[KEY]["explicit"] == []
    assert "source_message_id" not in session.entity_states[KEY]


@pytest.mark.parametrize(
    "broken",
    [
        {"actors": []},
        {"actors": {"LINA": []}},
        {"actors": {"LINA": {"posture": []}}},
        {"actors": {}, "explicit": None},
        {"actors": {}, "unconfirmed_actors": None},
    ],
)
def test_malformed_stored_staging_is_rejected_without_replacing_any_namespace(broken):
    session = state()
    session.entity_states[KEY] = {"scene_id": "START", "status": "ready", **broken}
    before = deepcopy(session.entity_states)
    with pytest.raises(ValueError, match="repair"):
        changed(session, posture="standing")
    assert session.entity_states == before


def test_repeating_the_same_host_command_is_a_noop_but_reusing_it_for_other_values_fails():
    session = state()
    first = changed(session, posture="kneeling")
    session.entity_states = first
    assert changed(session, posture="kneeling") == first
    with pytest.raises(ValueError, match="identity"):
        changed(session, posture="standing")


def test_invalid_legacy_staging_is_kept_for_repair_instead_of_overwritten():
    session = state()
    session.entity_states[KEY] = {
        "scene_id": "START",
        "status": "ready",
        "actors": {"hero": ["invalid"]},
    }
    before = deepcopy(session.entity_states)
    with pytest.raises(ValueError, match="repair"):
        changed(session, posture="standing")
    assert session.entity_states == before


def test_a_new_narrated_pose_does_not_keep_an_obsolete_command_dependency():
    session = state()
    session.entity_states = changed(session, posture="kneeling")
    text = "Lina stands up."
    from backend.engine.scene_staging.schema import SceneExtraction

    session.entity_states[KEY] = reconcile(
        session,
        CAST,
        text,
        SceneExtraction(changes=[{"entity_id": "LINA", "posture": "standing", "evidence": text}]),
    )
    stamp(session, SimpleNamespace(id="new-narration", revision_id="new-revision", content=text))
    copied = remap(session.entity_states, {"new-narration": "copy-narration"})
    assert (
        project(SimpleNamespace(current_scene_id="START", entity_states=copied), CAST)["LINA"][
            "posture"
        ]
        == "standing"
    )


@pytest.mark.parametrize(
    "update", [{"is_in_inventory": True}, {"is_hidden": True}, {"current_scene_id": "OTHER"}]
)
def test_a_bound_object_relation_becomes_unknown_when_the_canonical_object_leaves_view(update):
    session = state()
    session.entity_states = changed(
        session,
        posture="kneeling",
        placement=Placement(relation="near", target_kind="scene_object", target="BENCH"),
        operation="approach",
        scene_objects={"BENCH": "Oak bench"},
    )
    session.entity_states["BENCH"] = update
    assert project(session, CAST)["LINA"] == {"posture": "kneeling"}
