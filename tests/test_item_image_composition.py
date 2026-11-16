"""Item composition is task-owned across presets, adapters and image providers."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.core.image_prompt_rules import ImagePromptRules
from backend.core.item_image_prompts import item_provider_options
from backend.engine import image_prompt_adapter
from backend.engine.media_engine import MediaEngine
from backend.engine.media_generation import _prepare_prompt
from tests.test_comfyui import comfy_options, workflow
from tests.test_comfyui_presets import preset_options

__all__ = ["comfy_options", "workflow"]


@pytest.mark.parametrize("prepared", [False, True])
@pytest.mark.parametrize("adapt", [False, True])
async def test_item_constraint_survives_manual_and_adapted_comfy_workflows(
    comfy_options, workflow, monkeypatch, prepared, adapt
):
    options = preset_options(comfy_options, workflow)
    options["image_purpose"] = "object"
    options["_prompt_prepared"] = prepared
    options["_prompt_user"] = object()
    options["comfyui_presets"]["art"]["prompt_rules"]["adapt_with_llm"] = adapt
    call = AsyncMock(return_value="white medical coat, fine seams, pearl buttons")
    monkeypatch.setattr(
        image_prompt_adapter.GameMasterLLM,
        "for_role",
        lambda *_: SimpleNamespace(model="mock", aexecute_simple_task=call),
    )
    result = await image_prompt_adapter.prepare_prompt(
        "A white medical coat belonging to Dr Rin.", options
    )
    assert "Object-only" in result["positive"]
    assert "hangers" in result["positive"]
    assert "living creatures" in result["positive"]
    assert "hanger" in result["negative"]
    assert "human" in result["negative"]
    assert call.call_count == int(adapt and not prepared)
    if call.called:
        system = call.call_args.kwargs["system_prompt"]
        assert "not its owner wearing it" in system
        assert "hangers" in system


@pytest.mark.parametrize(
    "purpose", ["npc", "protagonist", "illustration", "background", "cover", "catalog"]
)
async def test_item_constraints_never_leak_to_other_image_tasks(comfy_options, workflow, purpose):
    options = preset_options(comfy_options, workflow)
    options["image_purpose"] = purpose
    options["visual_target_type"] = "object" if purpose == "catalog" else purpose
    options["_prompt_prepared"] = True
    result = await image_prompt_adapter.prepare_prompt("A traveler holding a lantern.", options)
    assert "Object-only" not in result["positive"]
    assert "hanger" not in result["negative"]
    assert "human" not in result["negative"]


@pytest.mark.parametrize("provider", ["openai", "stable_diffusion", "ollama", "comfyui"])
def test_legacy_and_other_provider_prompts_keep_task_composition(provider):
    options = {"image_purpose": "object"}
    prompt = _prepare_prompt(MediaEngine, "A white coat.", provider, options, "Anime")
    assert "Object-only" in prompt
    assert "hangers" in prompt
    assert (
        _prepare_prompt(MediaEngine, prompt, provider, options, "Anime").count("Object-only") == 1
    )


async def test_item_adapter_requires_flat_empty_clothing_without_a_hanger(monkeypatch):
    call = AsyncMock(return_value="A white coat laid flat on a dark surface.")
    monkeypatch.setattr(
        image_prompt_adapter.GameMasterLLM,
        "for_role",
        lambda *_: SimpleNamespace(model="mock", aexecute_simple_task=call),
    )
    await image_prompt_adapter.adapt_body(
        "The doctor's white coat.", ImagePromptRules(), object(), purpose="object"
    )
    system = call.call_args.kwargs["system_prompt"]
    assert "laid flat" in system
    assert "hangers" in system
    assert "not its owner wearing it" in system


async def test_item_preview_carries_its_task_into_adapter_and_final_prompt(
    auth_client, comfy_options, workflow, monkeypatch
):
    options = preset_options(comfy_options, workflow)
    call = AsyncMock(return_value="An embroidered coat laid flat on a wooden table.")
    monkeypatch.setattr(
        image_prompt_adapter.GameMasterLLM,
        "for_role",
        lambda *_: SimpleNamespace(model="mock", aexecute_simple_task=call),
    )
    response = await auth_client.post(
        "/api/settings/comfyui/preview-prompt",
        json={
            "preset": options["comfyui_presets"]["art"],
            "description": "The doctor's embroidered coat.",
            "image_purpose": "object",
        },
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert "Object-only" in result["positive"]
    assert "laid flat" in result["positive"]
    assert "hanger" in result["negative"]
    assert "not its owner wearing it" in call.call_args.kwargs["system_prompt"]


@pytest.mark.parametrize("provider", ["stable_diffusion", "ollama", "comfyui", "openai"])
def test_task_negative_preserves_settings_and_only_targets_supported_providers(provider):
    options = {"image_purpose": "object", "negative_prompt": "blurry"}
    result = item_provider_options(options, provider)
    assert options == {"image_purpose": "object", "negative_prompt": "blurry"}
    assert result["negative_prompt"].startswith("blurry")
    assert ("hanger" in result["negative_prompt"]) == (provider != "openai")
