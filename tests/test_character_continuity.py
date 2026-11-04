"""Remembered affect must not replace personality or become a current command."""

import json
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from backend.engine.visual_novel.character_context import narrator_character, remembered_direction
from backend.engine.visual_novel.prompts import narrator_context
from backend.engine.visual_novel.schema import InteractionPlan
from backend.engine.visual_novel.social import _payload, plan_interaction
from backend.engine.visual_novel.state import load_state, save_state
from tests.test_vn_social import manager_with_state, npc, proposal, seeded


def observed_character():
    social, character = seeded()
    character.emotion = "hurt"
    character.emotion_cause = "Lina withdrew after their argument."
    character.emotion_source_message_id = "PREVIOUS_SCENE"
    character.next_intention = "withdraw"
    character.relationship.trust = -12
    return social, character


@pytest.mark.parametrize("source", ["", "NEW_SCENE", "PREVIOUS_SCENE"])
def test_feelings_have_provenance_and_never_erase_identity_or_relationships(source):
    social, character = observed_character()
    before = deepcopy(social.model_dump())
    actor = npc(metadata_json={"personality_profile": {"speech": "ironic", "value": "family"}})
    projected = narrator_character(actor, character, source_message_id=source)
    status = "latest_completed_scene" if source == "PREVIOUS_SCENE" else "historical_reassess"
    assert projected["remembered_direction"]["status"] == status
    assert projected["remembered_direction"]["last_observed_emotion"] == "hurt"
    assert "emotion" not in projected and "next_intention" not in projected
    assert projected["goals"] == character.goals
    assert projected["core"] == character.core
    assert "dry humor" in projected["personality_tendencies"]
    assert "family" in projected["personality_tendencies"]
    assert projected["private_relationship_guidance"]["trust"] == -12
    assert social.model_dump() == before


def test_legacy_unproven_emotion_is_not_promoted_to_current_fact():
    _, character = seeded()
    character.emotion = "pleased"
    character.emotion_cause = "An old untracked feeling."
    result = remembered_direction(character, "NEW")
    assert result["status"] == "unconfirmed"
    assert "last_observed_emotion" not in result
    assert character.emotion == "pleased"


def test_planner_and_narrator_both_receive_historical_direction_as_history():
    social, _ = observed_character()
    data = json.loads(
        _payload(social, [npc()], "Where is the library?", "New room.", [], source_message_id="NEW")
    )
    planned = data["present_cast"][0]["character"]
    assert planned["remembered_direction"]["status"] == "historical_reassess"
    assert "next_intention" not in planned
    narrated = narrator_context(social, [npc()], source_message_id="NEW")
    assert '"status": "historical_reassess"' in narrated
    assert "not an inventory of traits" in narrated
    assert "does not erase emotional consequences" in narrated


@pytest.mark.asyncio
async def test_new_scene_reaction_is_tentative_while_prior_feelings_remain_saved():
    manager = manager_with_state()
    social, original = observed_character()
    save_state(manager.state, social)
    reaction = proposal(
        source="player_action",
        evidence="Where is the library?",
        event="none",
        emotion="guarded",
        intention="clarify",
    )
    llm = SimpleNamespace(
        model="small",
        aexecute_complex_task=AsyncMock(return_value=InteractionPlan(reactions=[reaction])),
    )
    with (
        patch("backend.engine.visual_novel.social._present_npcs", AsyncMock(return_value=[npc()])),
        patch(
            "backend.engine.visual_novel.social._scene_evidence", AsyncMock(return_value=("", ""))
        ),
        patch("backend.engine.visual_novel.social.GameMasterLLM.for_role", return_value=llm),
    ):
        result = await plan_interaction(manager, reaction.evidence, [], SimpleNamespace())
    assert '"status": "historical_reassess"' in result
    assert '"tentative_reaction_to_current_input"' in result
    assert '"emotion": "guarded"' in result
    assert '"intention": "clarify"' in result
    saved = load_state(manager.state).characters["LINA"]
    assert saved.emotion == original.emotion == "hurt"
    assert saved.next_intention == "withdraw"
    assert saved.relationship == original.relationship
    assert saved.core == original.core and saved.goals == original.goals
