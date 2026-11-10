"""Scene context stays bounded, private and compatible with older source hashes."""

import json
from types import SimpleNamespace

import pytest

from backend.core.text_evidence import EvidenceSpan
from backend.engine.chpm import host_observations, recent_scene, semantic_recall
from backend.engine.chpm.host_observation_contracts import (
    MAX_SCENE_CHARS,
    HostFacts,
    ObservedScene,
    ObservedSceneAction,
    PhysicalFact,
    SceneFact,
)
from backend.engine.chpm.host_state import record
from backend.engine.chpm.schema import Perception
from tests.test_chpm_host_state import mind, source


def action(quote):
    return ObservedSceneAction(
        actor_ids=("npc",), quote=quote, evidence_span=EvidenceSpan(start=0, end=len(quote))
    )


METADATA = {
    "source_message_id": "scene-source",
    "source_revision_id": None,
    "source_hash": "a" * 64,
    "scene_id": "room",
    "recorded_minute": 10,
}


def test_bounded_projection_retains_whole_quotes_and_rejects_oversized_saved_views():
    actions = [action(character * 600) for character in "abcd"]
    view = recent_scene._bounded(actions, METADATA, len(actions))
    assert view is not None
    assert len(json.dumps(view.model_dump(mode="json"), ensure_ascii=False)) <= MAX_SCENE_CHARS
    assert view.omitted_actions == len(actions) - len(view.actions) > 0
    assert all(row in actions for row in view.actions)
    assert ObservedScene.model_validate_json(view.model_dump_json()) == view
    with pytest.raises(ValueError, match="budget"):
        ObservedScene(**METADATA, actions=tuple(actions))


def test_observer_private_body_and_scene_facts_are_not_added_to_shared_narration():
    moment = recent_scene._bounded([action("The rescue team waits by the door.")], METADATA, 1)
    facts = HostFacts(
        scene_id="room",
        last_observed_scene=moment,
        physical_conditions=(
            PhysicalFact(
                id="injury",
                target_id="npc",
                kind="injury",
                part="neck",
                detail="PRIVATE_INJURY",
                status="active",
            ),
        ),
        scene_facts=(
            SceneFact(
                id="secret",
                subject_id="room",
                kind="process",
                detail="PRIVATE_PROCESS",
                status="active",
                recorded_minute=1,
                updated_minute=1,
            ),
        ),
    )
    original = record(
        mind(),
        source(kind="host_frame", text=host_observations.frame(facts)).model_copy(
            update={"facts": facts}
        ),
        minute=10,
    )
    shared = host_observations.situation(original)
    assert shared["last_observed_scene"] == moment.model_dump(mode="json")
    assert "PRIVATE" not in json.dumps(shared)
    assert "PRIVATE_INJURY" in host_observations.frame(facts)


def test_legacy_unknown_scene_keeps_the_exact_serialized_host_shape():
    legacy = {
        "scene_id": "room",
        "visible_actor_ids": [],
        "owned_items": None,
        "worn_item_ids": None,
    }
    assert HostFacts.model_validate(legacy).model_dump(mode="json") == legacy
    assert not host_observations.situation(mind())


def test_memory_query_preserves_existing_goal_cues_when_adding_a_large_scene():
    turn = SimpleNamespace(
        perceptions={"npc": Perception(actor_id="npc", quotes=["q" * 1600])},
        causal_threads={
            "npc": [
                SimpleNamespace(
                    closure=None,
                    facts={"purpose": SimpleNamespace(text="x" * 980 + " CRUCIAL_GOAL")},
                )
            ]
        },
        scene_cues={},
    )
    previous = semantic_recall._query(turn, "npc", "room")
    turn.scene_cues["npc"] = "s" * 1200
    current = semantic_recall._query(turn, "npc", "room")
    assert current.endswith(previous)
    assert "CRUCIAL_GOAL" in current
    assert len(current) <= 3000


def test_player_alias_is_translated_without_changing_original_source_text():
    quote = "The player waits near the door."
    row = SimpleNamespace(actor_ids=["__player__"], evidence=quote, evidence_span=None)
    translated = recent_scene._action(row, SimpleNamespace(content=quote), {"__player__"})
    assert translated.actor_ids == ("@player",)
    assert translated.quote == quote
    assert translated.evidence_span.matches(quote, quote)
    assert recent_scene._action(row, SimpleNamespace(content=quote), set()) is None
