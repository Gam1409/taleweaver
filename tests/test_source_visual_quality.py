"""Neutral source-rich mode preserves inputs without changing established routing."""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.core.config import settings
from backend.engine.scene_illustrations import render, source_quality
from backend.engine.scene_illustrations.visual_context import VisualContext
from tests.test_scene_illustrations import illustration_world

__all__ = ["illustration_world"]


def test_experiment_is_opt_in_and_leaves_adult_route_unchanged(monkeypatch):
    monkeypatch.setattr(settings, "VISUAL_SCENE_CONTEXT_MODE", "bounded")
    assert not source_quality.enabled({})
    monkeypatch.setattr(settings, "VISUAL_SCENE_CONTEXT_MODE", "neutral_source")
    assert source_quality.enabled({})
    assert not source_quality.enabled({"_nsfw_enabled": True})


def test_source_contains_full_scene_and_canonical_clothing_without_mutation():
    snapshot = {
        "narration": "[surprised] <breath> Anna steps away from Boris. A red notebook lies on the table.",
        "visible_facts": {
            "characters": [{"id": "ANNA", "clothing": "gray coat", "managed_clothing": True}]
        },
    }
    before = deepcopy(snapshot)
    prompt = source_quality.build_prompt(VisualContext.from_snapshot(snapshot), "watercolor")
    for expected in ("[surprised]", "steps away", "red notebook", "gray coat", "watercolor"):
        assert expected in prompt
    assert "<breath>" not in prompt
    assert snapshot == before


def test_oversize_source_fails_explicitly_without_cutting():
    context = VisualContext("x" * (source_quality.MAX_SCENE_CHARS + 1), {}, "")
    with pytest.raises(ValueError, match="no text was silently truncated"):
        source_quality.build_prompt(context)


@pytest.mark.asyncio
async def test_source_mode_uses_one_adaptation_and_no_enum_extraction(monkeypatch):
    monkeypatch.setattr(settings, "VISUAL_SCENE_CONTEXT_MODE", "neutral_source")
    monkeypatch.setattr(
        render,
        "_settings",
        AsyncMock(return_value=({"provider": "stable_diffusion"}, "watercolor", "quiet")),
    )
    extract = AsyncMock(side_effect=AssertionError("Source mode must not discard the passage"))
    adapt = AsyncMock(return_value="Two adults standing apart beside a table with a red notebook.")
    monkeypatch.setattr(render, "extract_frame", extract)
    monkeypatch.setattr(render, "adapt_body", adapt)
    snapshot = {
        "narration": "old suffix",
        "full_narration": "Full beginning. A red notebook is on the table.",
        "visible_facts": {
            "characters": [{"id": "ANNA", "managed_clothing": True, "clothing": "gray coat"}]
        },
    }
    request, _ = await render.image_request(
        None,
        SimpleNamespace(session_id="neutral-test"),
        SimpleNamespace(encrypted_api_keys={}),
        snapshot,
    )
    await render.prepare_moment_prompt(request)
    extract.assert_not_awaited()
    adapt.assert_awaited_once()
    source, policy, _ = adapt.call_args.args
    assert "Full beginning." in source
    assert "red notebook" in source
    assert "gray coat" in source
    assert "watercolor" in source
    assert "non-graphic illustration" in policy.instructions
    assert request["provider_options"]["_prompt_prepared"] is True


@pytest.mark.asyncio
async def test_owner_route_records_selected_mode(auth_client, illustration_world, monkeypatch):
    from tests.test_scene_illustrations import finish

    monkeypatch.setattr(settings, "VISUAL_SCENE_CONTEXT_MODE", "neutral_source")
    result = await finish(auth_client)
    assert result["state"] == "succeeded", result
    assert result["result"]["generation_details"]["context_mode"] == "neutral_source"
    assert illustration_world[0]["provider_options"]["_neutral_source"] is True
