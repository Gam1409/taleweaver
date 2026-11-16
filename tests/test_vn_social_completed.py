"""Completed interactions must survive planning a different immediate reaction."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from backend.engine.visual_novel.schema import MAX_PROCESSED, InteractionPlan
from backend.engine.visual_novel.social import apply_plan, plan_interaction
from backend.engine.visual_novel.state import ensure_character, load_state
from tests.test_vn_social import manager_with_state, npc, proposal, seeded


def test_completed_boundary_and_new_question_have_independent_provenance():
    social, character = seeded()
    observed = proposal(
        evidence="Лина отступила и потребовала больше её не трогать.",
        event="boundary_violated",
        emotion="angry",
        intention="set_boundary",
    )
    question = proposal(
        source="player_action",
        evidence="Я спрашиваю, где находится библиотека.",
        event="none",
        emotion="guarded",
        intention="clarify",
    )
    plan = InteractionPlan(completed_events=[observed], reactions=[question])
    directed = apply_plan(
        social, plan, [npc()], question.evidence, observed.evidence, "NARRATION_1"
    )
    assert character.relationship.trust == -2
    assert character.relationship.tension == 3
    assert character.emotion == "angry"
    assert character.memories[0].source_message_id == "NARRATION_1"
    assert character.memories[0].evidence == observed.evidence
    assert directed.characters["LINA"].emotion == "guarded"
    assert directed.characters["LINA"].relationship == character.relationship
    assert social.reviewed_scene_message_ids == ["NARRATION_1"]


@pytest.mark.parametrize("event", ["none", "cooperation"])
def test_observed_emotion_does_not_require_points_or_promotion(event):
    social, character = seeded()
    character.last_positive_turn = social.turn  # Any cooperation points are on cooldown.
    observed = proposal(event=event, emotion="concerned", intention="clarify")
    apply_plan(
        social, InteractionPlan(completed_events=[observed]), [npc()], "", observed.evidence, "N1"
    )
    assert character.emotion == "concerned"
    assert character.emotion_cause == observed.evidence
    assert character.next_intention == "clarify"
    assert character.relationship.trust == 0
    assert character.meaningful_events == 0
    assert character.memories == []


def test_repeated_scene_cannot_rewrite_observed_emotion_or_add_scores():
    social, character = seeded()
    observed = proposal(event="conflict", emotion="angry")
    apply_plan(
        social, InteractionPlan(completed_events=[observed]), [npc()], "", observed.evidence, "N1"
    )
    repeated = observed.model_copy(update={"emotion": "pleased", "event": "support"})
    social.turn += 10
    apply_plan(
        social, InteractionPlan(completed_events=[repeated]), [npc()], "", observed.evidence, "N1"
    )
    assert character.emotion == "angry"
    assert character.relationship.trust == 0
    assert character.relationship.tension == 2
    assert len(character.memories) == 1
    assert social.reviewed_scene_message_ids == ["N1"]


def test_completed_list_cannot_promote_player_assertions_to_facts():
    social, character = seeded()
    claim = proposal(source="player_action", evidence="She trusts me completely.")
    apply_plan(social, InteractionPlan(completed_events=[claim]), [npc()], claim.evidence, "", "N1")
    assert character.emotion == "neutral"
    assert character.memories == []
    assert character.relationship.trust == 0


@pytest.mark.parametrize(
    "intention", ["initiate", "pursue_goal", "challenge", "propose_activity", "investigate"]
)
def test_proactive_reaction_is_available_without_becoming_a_completed_event(intention):
    social, character = seeded()
    reaction = proposal(
        source="player_action",
        evidence="I ask about the letter.",
        event="none",
        intention=intention,
    )
    directed = apply_plan(
        social, InteractionPlan(reactions=[reaction]), [npc()], reaction.evidence, "", ""
    )
    assert directed.characters["LINA"].next_intention == intention
    assert character.next_intention == "listen"
    assert character.memories == []
    assert character.relationship.trust == 0


def test_reviewed_scene_ids_are_bounded_even_for_empty_observations():
    social, _ = seeded()
    for i in range(MAX_PROCESSED + 10):
        apply_plan(social, InteractionPlan(), [npc()], "", "Quiet room.", str(i))
    assert len(social.reviewed_scene_message_ids) == MAX_PROCESSED
    assert social.reviewed_scene_message_ids[0] == "10"


def test_missing_authored_core_hydrates_without_overwriting_established_goals():
    social, character = seeded()
    character.core = ""
    original_goals = list(character.goals)
    updated = npc(character="Keeps her promises.", goal="A different authored goal.")
    ensure_character(social, updated)
    assert character.core == "Keeps her promises."
    assert character.goals == original_goals
    character.goals = []
    ensure_character(social, updated)
    assert character.goals == ["A different authored goal."]


@pytest.mark.asyncio
async def test_failed_completed_review_can_retry_same_input_and_commits_once():
    manager = manager_with_state()
    observed = proposal(event="boundary_violated", emotion="guarded")
    plan = InteractionPlan(completed_events=[observed])
    llm = SimpleNamespace(
        model="small", aexecute_complex_task=AsyncMock(side_effect=[TimeoutError(), plan])
    )
    with (
        patch("backend.engine.visual_novel.social._present_npcs", AsyncMock(return_value=[npc()])),
        patch(
            "backend.engine.visual_novel.social._scene_evidence",
            AsyncMock(return_value=("N1", observed.evidence)),
        ),
        patch("backend.engine.visual_novel.social.GameMasterLLM.for_role", return_value=llm),
    ):
        await plan_interaction(manager, "Hello", [], SimpleNamespace())
        failed = load_state(manager.state)
        assert failed.reviewed_scene_message_ids == []
        assert failed.processed_message_ids == []
        await plan_interaction(manager, "Hello", [], SimpleNamespace())
        await plan_interaction(manager, "Hello", [], SimpleNamespace())
    assert llm.aexecute_complex_task.await_count == 2
    saved = load_state(manager.state)
    assert saved.reviewed_scene_message_ids == ["N1"]
    assert saved.processed_message_ids == ["PLAYER_1"]
    assert saved.characters["LINA"].relationship.trust == -2
    assert len(saved.characters["LINA"].memories) == 1
