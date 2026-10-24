"""Starter graphs exercise the same render/upload contract as imported workflows."""

import copy
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from backend.core.comfyui_config import ComfyPreset, ComfyWorkflow
from backend.core.comfyui_starters import FAMILIES, model_choices, starter_workflow
from backend.core.config import settings
from backend.core.llm_router import GameMasterLLM
from backend.engine.comfyui_client import ComfyClient
from backend.engine.comfyui_images import generate_comfy_image
from backend.engine.comfyui_output import bounded_dimensions
from backend.engine.image_prompt_adapter import (
    MATURE_THEMES_INSTRUCTION,
    asset_source,
    prepare_prompt,
)
from backend.models.user import User
from tests.conftest import TestSessionLocal
from tests.test_comfyui import fake_comfy
from tests.test_comfyui_output import png_bytes

__all__ = ["fake_comfy"]


@pytest.mark.parametrize("family", list(FAMILIES))
@pytest.mark.parametrize(
    ("target", "expected"),
    [
        ("cover", (1024, 512)),
        ("scene", (1024, 576)),
        ("npc", (816, 1024)),
        ("protagonist", (816, 1024)),
        ("object", (1024, 1024)),
    ],
)
@pytest.mark.asyncio
async def test_starters_render_asset_dimensions_without_manual_inputs(
    family, target, expected, fake_comfy, monkeypatch, tmp_path
):
    monkeypatch.setattr(settings, "DATA_DIR", str(tmp_path))
    workflow = starter_workflow(family)
    options = {
        "comfyui_profiles": {"simple": {"generate": workflow.model_dump()}},
        "visual_target_type": target,
        "simple_min_long_edge": 1024,
        "seed": 123,
    }
    original = copy.deepcopy(options)
    await generate_comfy_image('A lantern. "海"', options, str(tmp_path), "asset")
    graph = json.loads(next(r.content for r in fake_comfy if r.url.path == "/prompt"))["prompt"]
    assert tuple(graph["latent"]["inputs"][key] for key in ("width", "height")) == expected
    assert graph["sampler"]["inputs"]["seed"] == 123
    binding = workflow.bindings["prompt"]
    assert graph[binding.node_id]["inputs"][binding.input_name] == 'A lantern. "海"'
    assert graph["sampler"]["inputs"]["cfg"] == FAMILIES[family]["cfg"]
    assert options == original


@pytest.mark.parametrize("family", list(FAMILIES))
@pytest.mark.asyncio
async def test_reference_starters_upload_and_resize_without_changing_saved_workflow(
    family, fake_comfy, monkeypatch, tmp_path
):
    monkeypatch.setattr(settings, "DATA_DIR", str(tmp_path))
    (tmp_path / "previous.png").write_bytes(png_bytes((100, 80)))
    workflow = starter_workflow(family, reference=True)
    options = {
        "comfyui_profiles": {"simple": {"reference": workflow.model_dump()}},
        "reference_image_url": "/data/previous.png",
        "visual_target_type": "scene",
        "simple_min_long_edge": 1024,
    }
    await generate_comfy_image("The same harbor at dusk", options, str(tmp_path), "new")
    graph = json.loads(next(r.content for r in fake_comfy if r.url.path == "/prompt"))["prompt"]
    assert graph["input"]["inputs"]["image"] == "refs/uploaded.png"
    assert graph["resize"]["inputs"]["width"] == 1024
    assert graph["resize"]["inputs"]["height"] == 576
    assert graph["sampler"]["inputs"]["denoise"] == 0.3
    assert workflow.graph["input"]["inputs"]["image"] == "reference.png"
    assert (tmp_path / "previous.png").exists()


@pytest.mark.asyncio
async def test_saved_null_dimensions_still_use_portrait_defaults(fake_comfy, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "DATA_DIR", str(tmp_path))
    options = {
        "comfyui_profiles": {"simple": {"generate": starter_workflow("anima").model_dump()}},
        "visual_target_type": "protagonist",
        "simple_min_long_edge": 1024,
        "width": None,
        "height": None,
    }
    await generate_comfy_image("Portrait", options, str(tmp_path), "avatar")
    graph = json.loads(next(r.content for r in fake_comfy if r.url.path == "/prompt"))["prompt"]
    assert graph["latent"]["inputs"]["width"] == 816
    assert graph["latent"]["inputs"]["height"] == 1024


@pytest.mark.parametrize("family", list(FAMILIES))
def test_starter_family_detection_includes_reference_and_keeps_generation_controls(family):
    preset = ComfyPreset(
        name=family,
        generate=starter_workflow(family),
        reference=starter_workflow(family, True),
        auto_prompt_template=True,
    )
    assert preset.prompt_rules.template_id == family
    assert preset.reference.graph["sampler"]["inputs"]["denoise"] == 0.3
    assert preset.generate.graph["sampler"]["inputs"]["denoise"] == 1.0


def test_flux_and_anima_use_different_loaders_and_latents():
    flux = starter_workflow("flux1").graph
    anima = starter_workflow("anima").graph
    assert flux["model"]["class_type"] == "CheckpointLoaderSimple"
    assert flux["positive"]["inputs"]["clip_l"] == flux["positive"]["inputs"]["t5xxl"]
    assert flux["latent"]["class_type"] == "EmptySD3LatentImage"
    assert anima["model"]["class_type"] == "UNETLoader"
    assert anima["clip"]["inputs"]["type"] == "stable_diffusion"
    assert anima["latent"]["class_type"] == "EmptyLatentImage"
    assert anima["sampler"]["inputs"]["sampler_name"] == "er_sde"


@pytest.mark.parametrize("multiple", [8, 16, 32, 64])
def test_custom_dimensions_align_and_stay_inside_existing_limits(multiple):
    result = bounded_dimensions(
        {"visual_target_type": "scene", "width": 1801, "height": 1001}, multiple
    )
    assert result["width"] <= 1600 and result["height"] <= 900
    assert all(value % multiple == 0 for value in result.values())
    assert bounded_dimensions({"width": 1001}, multiple)["width"] % multiple == 0


@pytest.mark.asyncio
async def test_starter_catalog_is_admin_only_and_returns_valid_graphs(auth_client):
    response = await auth_client.get("/api/settings/comfyui/starter-workflows")
    assert response.status_code == 200
    assert {item["id"] for item in response.json()} == set(FAMILIES)
    for item in response.json():
        assert ComfyWorkflow.model_validate(item["generate"])
        assert "image" in ComfyWorkflow.model_validate(item["reference"]).bindings
    async with TestSessionLocal() as db:
        user = (await db.execute(select(User))).scalars().first()
        user.role = "user"
        await db.commit()
    assert (await auth_client.get("/api/settings/comfyui/starter-workflows")).status_code == 403
    response = await auth_client.post(
        "/api/settings/comfyui/model-options",
        json={"url": "http://127.0.0.1:8188", "workflow": starter_workflow("sdxl").model_dump()},
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_model_options_return_server_paths_and_sampler_choices(auth_client, monkeypatch):
    monkeypatch.setattr(settings, "ALLOW_PRIVATE_NETWORK_MODELS", True)
    registry = {
        "CheckpointLoaderSimple": {
            "input": {"required": {"ckpt_name": [["SDXL/sd_xl_base_1.0.safetensors"]]}}
        },
        "KSampler": {"input": {"required": {"sampler_name": [["euler", "er_sde"]]}}},
    }
    request = AsyncMock(return_value=registry)
    monkeypatch.setattr(ComfyClient, "json", request)
    workflow = starter_workflow("sdxl")
    response = await auth_client.post(
        "/api/settings/comfyui/model-options",
        json={"url": "http://127.0.0.1:8188", "workflow": workflow.model_dump()},
    )
    assert response.status_code == 200
    assert response.json()[0]["choices"] == ["SDXL/sd_xl_base_1.0.safetensors"]
    assert any(item["choices"] == ["euler", "er_sde"] for item in response.json())
    request.assert_awaited_once_with("GET", "/object_info")
    request.return_value = {"CheckpointLoaderSimple": None}
    response = await auth_client.post(
        "/api/settings/comfyui/model-options",
        json={"url": "http://127.0.0.1:8188", "workflow": workflow.model_dump()},
    )
    assert response.status_code == 400


def test_connected_loader_inputs_are_not_editable_filename_fields():
    workflow = starter_workflow("sdxl")
    workflow.graph["model"]["inputs"]["ckpt_name"] = ["custom", 0]
    assert all(item["input_name"] != "ckpt_name" for item in model_choices(workflow, {}))


def test_disabled_adapter_sends_visible_description_without_json_keys_or_plot():
    preset = ComfyPreset(
        name="Anima", generate=starter_workflow("anima"), auto_prompt_template=True
    )
    preset.auto_prompt_template = False
    preset.prompt_rules.adapt_with_llm = False
    options = {
        "simple_model_provider": "comfyui",
        "comfyui_presets": {"art": preset.model_dump()},
        "comfyui_assignments": {"simple": "art"},
    }
    result = asset_source(
        options,
        "object",
        "legacy boilerplate",
        name="The tide key",
        description="One brass key with a blue cord.",
        context="Hidden plot information",
    )
    assert result == "One brass key with a blue cord."


@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.asyncio
async def test_mature_theme_rule_is_opt_in_and_does_not_change_workflow(enabled, monkeypatch):
    preset = ComfyPreset(
        name="Anima",
        generate=starter_workflow("anima"),
        auto_prompt_template=True,
        mature_themes=enabled,
    )
    options = {
        "comfyui_presets": {"art": preset.model_dump()},
        "comfyui_assignments": {"simple": "art"},
        "_prompt_user": object(),
    }
    llm = SimpleNamespace(
        model="fake", aexecute_simple_task=AsyncMock(return_value="Two adults dancing.")
    )
    monkeypatch.setattr(GameMasterLLM, "for_role", lambda *_args: llm)
    graph = copy.deepcopy(preset.generate.graph)
    await prepare_prompt("Two adult partners dancing under lanterns.", options)
    system = llm.aexecute_simple_task.call_args.kwargs["system_prompt"]
    assert (MATURE_THEMES_INSTRUCTION in system) is enabled
    assert options["comfyui_presets"]["art"]["generate"]["graph"] == graph
    options["_prompt_prepared"] = True
    await prepare_prompt("A manually prepared portrait.", options)
    assert llm.aexecute_simple_task.await_count == 1


@pytest.mark.asyncio
async def test_theme_setting_survives_save_reload_and_automatic_template(auth_client, monkeypatch):
    monkeypatch.setattr(settings, "ALLOW_PRIVATE_NETWORK_MODELS", True)
    preset = ComfyPreset(
        name="Anima",
        generate=starter_workflow("anima"),
        auto_prompt_template=True,
        mature_themes=True,
    )
    options = {
        "simple_model_provider": "comfyui",
        "simple_model": "",
        "advanced_model": "unused",
        "advanced_model_provider": "openai",
        "provider": "comfyui",
        "comfyui_presets": {"art": preset.model_dump()},
        "comfyui_assignments": {"simple": "art"},
    }
    response = await auth_client.post("/api/settings/t2i", json=options)
    assert response.status_code == 200, response.text
    result = (await auth_client.get("/api/settings?include_available_constants=false")).json()
    saved = result["t2i_settings"]["comfyui_presets"]["art"]
    assert saved["mature_themes"] is True
    assert saved["auto_prompt_template"] is True
    assert saved["prompt_rules"]["template_id"] == "anima"
