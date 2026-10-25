"""VN presentation preserves state, player agency and legacy prompt contracts."""

from copy import deepcopy
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from backend.api.routes.adventures.turn_llm_pipeline import TurnLlmContextBuilder
from backend.core import prompts
from backend.engine.memory_manager import MemoryManager
from backend.engine.visual_novel.config import (
    SETTINGS_KEY,
    VnSettings,
    read_settings,
    write_settings,
)
from backend.engine.visual_novel.narration import narration_suffix


@pytest.mark.parametrize("pace", ["leisurely", "balanced", "brisk"])
def test_pace_preserves_canonical_state_and_common_agency_contract(pace):
    state = SimpleNamespace(
        entity_states={
            "npc_7": {"inventory": [{"id": "key"}]},
            "__vn_state__": {"trust": 12, "private_plan": "Wait until tomorrow"},
        }
    )
    original = deepcopy(state.entity_states)
    old_reference = state.entity_states

    write_settings(state, VnSettings(pace=pace))
    prompt = narration_suffix(state)

    assert state.entity_states is not old_reference
    assert old_reference == original
    assert state.entity_states["npc_7"] == original["npc_7"]
    assert state.entity_states["__vn_state__"] == original["__vn_state__"]
    assert state.entity_states[SETTINGS_KEY] == {"pace": pace}
    assert read_settings(state).pace == pace
    assert f"PACING: {pace.upper()}." in prompt
    assert "Stop before the next meaningful player decision" in prompt
    assert 'Character Name: "Dialogue"' in prompt
    assert "session's content language" in prompt
    assert "approved NPC movement in TURN RESOLUTION" in prompt
    assert "does not authorize leaving the room" in prompt
    assert "Never invent a destination" in prompt
    assert "Use CURRENT STATE's present cast" in prompt
    assert "CURRENT GAME TIME and the approved elapsed duration are authoritative" in prompt
    assert "Do not invent minutes passing" in prompt
    assert "not from the number of replies" in prompt
    assert "Wait until tomorrow" not in prompt
    assert "Sitcom" not in prompt


@pytest.mark.parametrize(
    "stored", [None, [], {}, {SETTINGS_KEY: None}, {SETTINGS_KEY: {"pace": "instant"}}]
)
def test_missing_or_invalid_settings_use_balanced_without_mutating_storage(stored):
    state = SimpleNamespace(entity_states=deepcopy(stored))
    assert read_settings(state).pace == "balanced"
    assert state.entity_states == stored


def test_unknown_preferences_are_rejected():
    with pytest.raises(ValidationError):
        VnSettings.model_validate({"pace": "brisk", "private_plan": "replace"})


@pytest.mark.parametrize("mode", [None, "strict", "rpg", "story", "chat"])
def test_legacy_modes_keep_exact_default_static_contract(mode):
    expected = prompts.GAME_MASTER_SYSTEM_PROMPT_TEMPLATE.format(
        plot="Explore and survive.",
        rules="Standard RPG rules apply.",
        walkthrough="No specific walkthrough guidance available.",
        completed_condition="No specific win condition set.",
        gameover_condition="No specific game over condition set.",
        world_context="A seaside town",
    )
    assert (
        MemoryManager.build_static_prompt("A seaside town", rule_enforcement_mode=mode) == expected
    )


def test_vn_context_builder_uses_session_frame_without_rpg_base():
    adventure = SimpleNamespace(
        original_prompt="A seaside town",
        plot="Template plot",
        rules="Template rules",
        walkthrough="Template guidance",
        completed_condition=None,
        gameover_condition=None,
        is_adventure_generator=False,
        rule_enforcement_mode="vn",
        sequences=[],
    )
    state = SimpleNamespace(
        plot="Session plot",
        rules="Session rules",
        walkthrough="A private promise",
        completed_condition="The reunion is resolved",
        gameover_condition=None,
        active_sequence_id=None,
    )

    result = TurnLlmContextBuilder(
        SimpleNamespace(state=state, adventure=adventure)
    )._build_static_prompt()

    assert "interactive visual novel" in result
    assert "Session plot" in result and "Session rules" in result
    assert "Template plot" not in result and "Template rules" not in result
    assert "A private promise" in result and "The reunion is resolved" in result
    assert "Text Adventure RPG" not in result
    assert "Standard RPG rules apply" not in result
    assert "chronological, linear sequences" not in result
    assert "not a mandatory solution" in result


def test_generator_retains_its_tool_contract_even_with_vn_mode():
    prompt = MemoryManager.build_static_prompt(
        "Create stories", is_adventure_generator=True, rule_enforcement_mode="vn"
    )
    assert prompts.ADVENTURE_GENERATOR_INSTRUCTIONS in prompt
    assert "Text Adventure RPG" in prompt
