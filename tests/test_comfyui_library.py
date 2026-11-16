"""Reusable graph snapshots do not alter the workflows pinned in presets."""

import copy

import pytest
from pydantic import ValidationError

from backend.core.comfyui_config import ComfySettings, select_workflow
from tests.test_comfyui import workflow
from tests.test_comfyui_presets import named_preset

__all__ = ["workflow"]


def test_library_roundtrip_and_pinned_generation(workflow):
    original = copy.deepcopy(workflow)
    options = {
        "comfyui_presets": {"art": named_preset(workflow)},
        "comfyui_assignments": {"simple": "art"},
        "comfyui_workflows": {"v1": {"revision": 1, "workflow": workflow}},
        "comfyui_test_preset": "art",
    }
    saved = ComfySettings.model_validate(options).model_dump()
    assert saved["comfyui_workflows"]["v1"]["revision"] == 1
    assert saved["comfyui_test_preset"] == "art"
    saved["comfyui_workflows"]["v1"]["workflow"]["graph"]["model"]["inputs"]["ckpt_name"] = (
        "other.ckpt"
    )
    assert select_workflow(saved).graph == original["graph"]
    saved["comfyui_workflows"] = {}
    assert select_workflow(saved).graph == original["graph"]


def test_unknown_test_preset_is_rejected():
    with pytest.raises(ValidationError, match="test preset is missing"):
        ComfySettings.model_validate({"comfyui_test_preset": "deleted"})


def test_invalid_library_graph_is_rejected():
    with pytest.raises(ValidationError):
        ComfySettings.model_validate(
            {"comfyui_workflows": {"bad": {"revision": 0, "workflow": {}}}}
        )


def test_reference_rules_are_selected_only_for_reference_requests(workflow):
    from backend.core.comfyui_config import prompt_rules
    from backend.core.image_prompt_templates import template_rules

    preset = named_preset(workflow)
    override = template_rules("sdxl").model_dump()
    override["prefix"] = "reference variant"
    preset["reference_prompt_rules"] = override
    options = {"comfyui_presets": {"art": preset}, "comfyui_assignments": {"simple": "art"}}
    assert prompt_rules(options).prefix != "reference variant"
    assert (
        prompt_rules({**options, "reference_image_url": "/data/reference.png"}).prefix
        == "reference variant"
    )
    preset["reference_prompt_rules"] = None
    assert prompt_rules({**options, "reference_image_url": "/data/reference.png"}) == prompt_rules(
        options
    )


def test_legacy_test_preset_migration_is_explicit_and_idempotent(workflow):
    from backend.core.comfyui_presets import normalize_comfy_presets

    options = {
        "simple_model_provider": "comfyui",
        "comfyui_presets": {"art": named_preset(workflow)},
        "comfyui_assignments": {"simple": "art"},
    }
    migrated = normalize_comfy_presets(options)
    assert migrated["comfyui_test_preset"] == "art"
    assert normalize_comfy_presets(migrated) == migrated
    migrated["comfyui_test_preset"] = None
    assert normalize_comfy_presets(migrated)["comfyui_test_preset"] is None


@pytest.mark.asyncio
async def test_library_and_reference_policy_persist_in_settings(auth_client, workflow, monkeypatch):
    from unittest.mock import AsyncMock

    from backend.api.routes import config_api
    from backend.core.config import settings
    from backend.core.image_prompt_templates import template_rules

    monkeypatch.setattr(settings, "ALLOW_PRIVATE_NETWORK_MODELS", True)
    monkeypatch.setattr(config_api, "_fetch_ollama_models", AsyncMock(return_value=[]))
    preset = named_preset(workflow)
    preset["reference_prompt_rules"] = template_rules("sdxl").model_dump()
    preset["reference_prompt_rules"]["prefix"] = "Reference composition"
    options = {
        "provider": "comfyui",
        "simple_model": "",
        "advanced_model": "",
        "simple_model_provider": "comfyui",
        "advanced_model_provider": "comfyui",
        "comfyui_url": "http://127.0.0.1:8188",
        "comfyui_presets": {"art": preset},
        "comfyui_assignments": {"simple": "art", "advanced": "art"},
        "comfyui_workflows": {"v1": {"revision": 1, "workflow": workflow}},
        "comfyui_test_preset": "art",
    }
    response = await auth_client.post("/api/settings/t2i", json=options)
    assert response.status_code == 200, response.text
    loaded = (await auth_client.get("/api/settings")).json()["t2i_settings"]
    assert loaded["comfyui_workflows"]["v1"]["workflow"]["graph"] == workflow["graph"]
    assert loaded["comfyui_test_preset"] == "art"
    assert (
        loaded["comfyui_presets"]["art"]["reference_prompt_rules"]["prefix"]
        == "Reference composition"
    )
