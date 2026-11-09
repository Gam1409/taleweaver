"""Source edits and partial history copies cannot retract unrelated character poses."""

from copy import deepcopy
from types import SimpleNamespace

from backend.engine.scene_staging.provenance import remap, retract, stamp
from backend.engine.scene_staging.schema import SceneExtraction
from backend.engine.scene_staging.state import KEY, project, reconcile
from tests.test_scene_staging import CAST, TEXT, extraction, state


def two_sources():
    current = state()
    current.entity_states[KEY] = reconcile(current, CAST, TEXT, extraction())
    stamp(current, SimpleNamespace(id="m1", revision_id="r1", content=TEXT))
    text = "Lina kneels beside Hero and kisses him."
    proposal = SceneExtraction(
        changes=[{"entity_id": "LINA", "posture": "kneeling", "evidence": text}],
        explicit=[{"category": "kissing", "participants": ["hero", "LINA"], "evidence": text}],
    )
    current.entity_states[KEY] = reconcile(current, CAST, text, proposal)
    stamp(current, SimpleNamespace(id="m2", revision_id="r2", content=text))
    return current


def test_retraction_unconfirms_only_actors_supported_by_that_message():
    current = two_sources()
    canonical = deepcopy(current.entity_states["LINA"])
    retract(current, "m2")
    assert project(current, CAST)["hero"]["posture"] == "sitting"
    assert "LINA" not in project(current, CAST)
    assert not current.entity_states[KEY].get("explicit")
    assert current.entity_states["LINA"] == canonical
    assert current.current_scene_id == "START"


def test_missing_copy_source_unconfirms_only_its_actor_and_clears_message_local_acts():
    current = two_sources()
    current.entity_states = remap(current.entity_states, {"m1": "c1"})
    assert project(current, CAST)["hero"]["posture"] == "sitting"
    assert "LINA" not in project(current, CAST)
    assert not current.entity_states[KEY].get("explicit")
    assert current.entity_states[KEY]["actors"]["hero"]["posture"]["source_message_id"] == "c1"


def test_a_complete_history_copy_preserves_both_poses_and_rebinds_each_source():
    current = two_sources()
    before = project(current, CAST)
    current.entity_states = remap(current.entity_states, {"m1": "c1", "m2": "c2"})
    assert project(current, CAST) == before
    assert current.entity_states[KEY]["source_message_id"] == "c2"
    assert current.entity_states[KEY]["actors"]["hero"]["posture"]["source_message_id"] == "c1"
