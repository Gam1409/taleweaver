"""Independent staging facts survive malformed sibling deltas."""

from backend.engine.scene_staging import shared
from backend.engine.scene_staging.schema import SceneExtraction
from backend.engine.scene_staging.state import KEY, project, reconcile
from tests.test_scene_staging import CAST, TEXT, extraction
from tests.test_scene_staging import state as staging_state
from tests.test_shared_staging_bindings import manager


def test_an_unrelated_invalid_pose_does_not_erase_previously_confirmed_actors():
    current = staging_state()
    current.entity_states[KEY] = reconcile(current, CAST, TEXT, extraction())
    before = project(current, CAST)
    assert before["hero"]["posture"] == "sitting"
    proposal = SceneExtraction.model_validate(
        {"changes": [{"entity_id": "ABSENT", "posture": "standing", "evidence": "Nobody moves."}]}
    )
    current.entity_states[KEY] = reconcile(current, CAST, "Nobody moves.", proposal)
    assert project(current, CAST) == before


def test_malformed_prop_does_not_discard_a_valid_independent_pose():
    current, actors, rows = manager()
    current.state.in_game_time = 0
    text = "Anna sits down."
    assert shared.begin(current, text)
    shared.prepare(current, actors, rows)
    shared.propose(
        current,
        {
            "staging": {
                "changes": [{"entity_id": "NPC", "posture": "sitting", "evidence": text}],
                "props": [{"item_action_index": -1, "owner_id": "NPC", "evidence": text}],
            }
        },
    )
    assert shared.consume(current, text, completed=True)
    assert project(current.state, [{"id": "NPC"}, {"id": "hero"}]).get("NPC") == {
        "posture": "sitting"
    }


def test_one_character_can_take_off_their_own_coat():
    text = "Lina takes off her coat."
    proposal = SceneExtraction.model_validate(
        {"explicit": [{"category": "undressing", "participants": ["LINA"], "evidence": text}]}
    )
    result = reconcile(staging_state(), CAST, text, proposal)
    assert result["explicit_rejected"] == 0
    assert result["explicit"][0]["category"] == "undressing"


def test_only_the_actor_with_an_unverifiable_new_pose_loses_confirmation():
    current = staging_state()
    current.entity_states[KEY] = reconcile(current, CAST, TEXT, extraction())
    proposal = SceneExtraction.model_validate(
        {
            "changes": [
                {"entity_id": "LINA", "posture": "sitting", "evidence": "A fabricated quote."}
            ]
        }
    )
    current.entity_states[KEY] = reconcile(current, CAST, "Lina sits down.", proposal)
    assert project(current, CAST)["hero"] == {
        "posture": "sitting",
        "placement": {"relation": "on", "target_kind": "scene_object", "target": "bench"},
    }
    assert "LINA" not in project(current, CAST)
    assert current.entity_states[KEY]["unconfirmed_actors"] == ["LINA"]


def test_a_pose_proposal_cannot_teleport_an_actor_to_a_different_scene():
    current, actors, rows = manager()
    text = "Anna sits down."
    before = current.state.current_scene_id
    shared.begin(current, text)
    shared.prepare(current, actors, rows)
    shared.propose(
        current,
        {
            "staging": {
                "changes": [
                    {
                        "entity_id": "NPC",
                        "posture": "sitting",
                        "evidence": text,
                        "scene_id": "OTHER",
                    }
                ],
            }
        },
    )
    assert shared.consume(current, text, completed=True)
    assert current.state.current_scene_id == before
    assert current.state.entity_states[KEY]["unconfirmed_actors"] == ["NPC"]
    assert project(current.state, [{"id": "NPC"}, {"id": "hero"}]) == {}


def test_invalid_sibling_pose_preserves_an_independent_confirmed_prop():
    from backend.engine.scene_staging.proposals import validate

    proposal = validate(
        {
            "changes": [{"entity_id": "NPC", "posture": "flying", "evidence": "Anna sits down."}],
            "props": [
                {
                    "item_id": "COAT",
                    "owner_id": "NPC",
                    "evidence": "Anna places the coat on the bench.",
                    "spatial_position": "bench",
                    "status": "confirmed",
                }
            ],
        }
    )
    assert proposal.unconfirmed_actors == {"NPC"}
    assert proposal.rejected == {"changes": 1, "props": 0, "explicit": 0}
    assert proposal.value.props[0].item_id == "COAT"


def test_malformed_explicit_atom_does_not_discard_a_valid_pose():
    current, actors, rows = manager()
    text = "Anna sits down."
    shared.begin(current, text)
    shared.prepare(current, actors, rows)
    shared.propose(
        current,
        {
            "staging": {
                "changes": [{"entity_id": "NPC", "posture": "sitting", "evidence": text}],
                "explicit": [
                    {"category": "unrecognized", "participants": ["NPC"], "evidence": text}
                ],
            }
        },
    )
    assert shared.consume(current, text, completed=True)
    assert project(current.state, [{"id": "NPC"}, {"id": "hero"}])["NPC"] == {"posture": "sitting"}
    assert current.state.entity_states[KEY]["explicit_rejected"] == 1


def test_schema_invalid_pose_is_counted_as_a_rejected_proposal(monkeypatch):
    from collections import Counter

    from backend.core import reliability_metrics

    monkeypatch.setattr(reliability_metrics, "_staging", Counter())
    current, actors, rows = manager()
    text = "Anna sits down."
    shared.begin(current, text)
    shared.prepare(current, actors, rows)
    shared.propose(
        current,
        {"staging": {"changes": [{"entity_id": "NPC", "posture": "flying", "evidence": text}]}},
    )
    assert shared.consume(current, text, completed=True)
    metrics = reliability_metrics.snapshot()["staging"]
    assert metrics["proposed_deltas"] == 1
    assert metrics["rejected_deltas"] == 1
    assert metrics["partial_turns"] == 1
