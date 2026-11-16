"""Mature additions are opt-in and do not replace existing prompt contracts."""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.core import mature_content_prompts
from backend.core.image_prompt_rules import ImagePromptRules
from backend.engine.image_prompt_adapter import adapt_body
from backend.engine.visual_novel.narration import narration_suffix


def session_state(enabled, level="hard"):
    return SimpleNamespace(
        entity_states={
            "__manifest_snapshot__": {
                "original_manifest": {"nsfw_settings": {"enabled": enabled, "level": level}}
            }
        }
    )


@pytest.mark.parametrize("enabled", [True, False, None, "true", 1])
def test_narrative_addition_uses_saved_nsfw_setting(enabled, monkeypatch):
    monkeypatch.setattr(
        mature_content_prompts, "narrative_addendum", lambda level: "Custom narrative addition"
    )
    state = session_state(enabled)
    original = deepcopy(state.entity_states)
    base = narration_suffix(session_state(False))
    result = narration_suffix(state)
    assert result == (base + "\n\nCustom narrative addition" if enabled is True else base)
    assert state.entity_states == original
    assert "CURRENT GAME TIME" in result
    assert "session's content language" in result
    assert "PACING: BALANCED" in result


@pytest.mark.parametrize("states", [None, [], {}, {"__manifest_snapshot__": []}])
def test_legacy_or_invalid_snapshot_does_not_enable_addition(states):
    prompt = narration_suffix(SimpleNamespace(entity_states=states))
    assert mature_content_prompts.narrative_addendum("hard") not in prompt


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.parametrize("kind", ["npc portrait", "scene illustration"])
async def test_image_addition_preserves_policy_and_visible_facts(enabled, kind, monkeypatch):
    monkeypatch.setattr(
        mature_content_prompts, "image_prompt_addendum", lambda level: "Custom image addition"
    )
    llm = SimpleNamespace(model="test", aexecute_simple_task=AsyncMock(return_value="A red coat"))
    monkeypatch.setattr(
        "backend.engine.image_prompt_adapter.GameMasterLLM.for_role", lambda *_args: llm
    )
    description = f"{kind}: adult traveler wearing a red coat"
    assert await adapt_body(
        description,
        ImagePromptRules(),
        object(),
        mature_themes=enabled,
        nsfw_enabled=enabled,
        nsfw_level="hard",
    )
    request = llm.aexecute_simple_task.call_args.kwargs
    assert request["user_prompt"] == description
    assert ("Custom image addition" in request["system_prompt"]) is enabled
    assert "Preserve the supplied visible facts" in request["system_prompt"]
    assert "Do not output JSON" in request["system_prompt"]
    assert mature_content_prompts.narrative_addendum("hard") not in request["system_prompt"]
