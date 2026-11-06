"""Standard presets are complete, editable, bounded and do not replace user settings."""

from copy import deepcopy
from unittest.mock import AsyncMock

import pytest

from backend.api.routes.settings_normalization import normalize_t2i_settings
from backend.core.comfyui_config import ComfySettings
from backend.core.comfyui_defaults import STANDARD_FAMILIES, standard_presets
from backend.core.comfyui_presets import normalize_comfy_presets
from backend.core.image_purposes import PURPOSES, purpose_target
from backend.core.visual_limits import visual_limits
from tests.test_comfyui_task_templates import check_links


def test_standard_library_covers_every_task_with_selected_workflows_and_rules():
    bundle = standard_presets()
    typed = ComfySettings.model_validate(bundle)
    assert len(typed.comfyui_presets) == 16 and len(typed.comfyui_workflows) == 28
    assert not typed.comfyui_assignments and typed.comfyui_test_preset is None
    for family in STANDARD_FAMILIES:
        for purpose in PURPOSES:
            identifier = f"standard-{family}-{purpose}"
            preset = typed.comfyui_presets[identifier]
            assert preset.prompt_rules.template_id == family
            assert preset.purpose_tags == [purpose] and not preset.auto_prompt_template
            assert preset.generate is not None
            assert typed.comfyui_workflows[identifier + "-generate"].workflow == preset.generate
            assert bool(preset.reference) == (purpose not in {"avatar", "catalog"})
            for workflow in (preset.generate, preset.reference):
                if workflow is None:
                    continue
                check_links(workflow.graph)
                bounds = visual_limits(purpose_target(purpose))
                for key, maximum in (("width", "maxWidth"), ("height", "maxHeight")):
                    binding = workflow.bindings[key]
                    value = workflow.graph[binding.node_id]["inputs"][binding.input_name]
                    assert 0 < value <= bounds[maximum] and value % workflow.dimension_multiple == 0
            classes = {node["class_type"] for node in preset.generate.graph.values()}
            if family == "anima":
                assert {"UNETLoader", "CLIPLoader", "VAELoader"}.issubset(classes)
                assert "CheckpointLoaderSimple" not in classes
            else:
                assert "CheckpointLoaderSimple" in classes
                assert not {"CLIPLoader", "VAELoader", "UNETLoader"}.intersection(classes)
    assert ComfySettings.model_validate_json(typed.model_dump_json()) == typed


def test_default_bootstrap_is_independent_and_explicit_deletions_stay_deleted():
    fresh = normalize_t2i_settings(None)
    assert len(fresh["comfyui_presets"]) == 16
    assert fresh["simple_model_provider"] == fresh["advanced_model_provider"] == "openai"
    assert not fresh["comfyui_assignments"]
    assert normalize_t2i_settings(fresh) == fresh
    original = deepcopy(standard_presets())
    fresh["comfyui_presets"]["standard-anima-npc"]["name"] = "Edited by user"
    fresh["comfyui_presets"]["standard-anima-npc"]["generate"]["graph"]["sampler"]["inputs"][
        "steps"
    ] = 1
    assert (
        fresh["comfyui_workflows"]["standard-anima-npc-generate"]
        == original["comfyui_workflows"]["standard-anima-npc-generate"]
    )
    assert standard_presets() == original
    deleted = {"comfyui_presets": {}, "comfyui_workflows": {}}
    assert normalize_comfy_presets(deleted)["comfyui_presets"] == {}
    existing = {"comfyui_presets": {"custom": {"name": "Custom"}}}
    assert normalize_comfy_presets(existing)["comfyui_presets"] == existing["comfyui_presets"]


@pytest.mark.asyncio
async def test_standard_presets_endpoint_and_settings_roundtrip(auth_client, monkeypatch):
    from backend.api.routes import config_api

    monkeypatch.setattr(config_api, "_fetch_ollama_models", AsyncMock(return_value=[]))
    response = await auth_client.get("/api/settings/comfyui/standard-presets")
    assert response.status_code == 200, response.text
    bundle = response.json()
    saved = await auth_client.post(
        "/api/settings/t2i",
        json={
            **bundle,
            "simple_model": "",
            "advanced_model": "",
            "provider": "openai",
            "simple_model_provider": "openai",
            "advanced_model_provider": "openai",
        },
    )
    assert saved.status_code == 200, saved.text
    loaded = (await auth_client.get("/api/settings?include_available_constants=false")).json()
    assert loaded["t2i_settings"]["comfyui_presets"] == bundle["comfyui_presets"]
    assert loaded["t2i_settings"]["comfyui_workflows"] == bundle["comfyui_workflows"]
