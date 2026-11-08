"""A successful test preset must not hide which task workflow was rejected."""

import copy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from backend.core.comfyui_errors import ComfyRequestError
from backend.core.error_diagnostics import diagnose_provider_error
from backend.engine.comfyui_client import ComfyClient
from backend.engine.comfyui_images import generate_comfy_image
from backend.engine.story_visual_presets import story_t2i
from tests.test_comfyui import workflow

__all__ = ["workflow"]


def test_model_details_exclude_full_paths_urls_and_unrelated_inputs(workflow):
    from backend.core.comfyui_config import ComfyWorkflow
    from backend.engine.comfyui_diagnostics import model_files

    workflow["graph"]["model"]["inputs"] = {
        "ckpt_name": "D:\\private-server-folder\\model.safetensors",
        "clip_name": "https://secret-host/model.safetensors?token=secret",
        "unknown": "private-token",
    }
    files = model_files(ComfyWorkflow.model_validate(workflow))
    assert len(files) == 1
    assert files[0]["file"] == "model.safetensors"
    assert "private" not in str(files)
    assert "secret" not in str(files)


@pytest.mark.asyncio
async def test_rejection_explains_missing_model_input_without_provider_body(monkeypatch):
    monkeypatch.setattr("backend.engine.comfyui_client.validate_provider_url", lambda url: url)
    async with ComfyClient("https://example.com") as client:
        monkeypatch.setattr(
            client.http,
            "request",
            AsyncMock(
                return_value=httpx.Response(
                    400,
                    json={
                        "node_errors": {
                            "model": {
                                "class_type": "UNETLoader",
                                "errors": [
                                    {
                                        "type": "value_not_in_list",
                                        "details": "secret-provider-path",
                                        "extra_info": {"input_name": "unet_name"},
                                    }
                                ],
                            }
                        }
                    },
                )
            ),
        )
        with pytest.raises(ComfyRequestError) as caught:
            await client.json("POST", "/prompt", json={"prompt": {}})
    message = str(caught.value)
    assert "unet_name" in message
    assert "not available" in message
    assert "secret-provider-path" not in message


@pytest.mark.asyncio
@pytest.mark.parametrize("saved", [False, True])
async def test_failed_generation_names_actual_task_preset_and_file(monkeypatch, workflow, saved):
    from backend.engine import comfyui_images

    task_workflow = copy.deepcopy(workflow)
    task_workflow["name"] = "Background workflow"
    task_workflow["graph"]["model"] = {
        "class_type": "UNETLoader",
        "inputs": {"unet_name": "missing-anima.safetensors", "weight_dtype": "default"},
    }
    tested_workflow = copy.deepcopy(task_workflow)
    tested_workflow["graph"]["model"]["inputs"]["unet_name"] = "installed-nova.safetensors"
    settings = {
        "comfyui_url": "https://example.com",
        "comfyui_presets": {
            "tested": {"name": "Nova Anima", "generate": tested_workflow},
            "background": {"name": "Anima backgrounds", "generate": task_workflow},
        },
        "comfyui_assignments": {"advanced": "tested", "background": "background"},
        "comfyui_test_preset": "tested",
    }
    story = SimpleNamespace(
        original_manifest={
            "visual_preset_source": "saved" if saved else "current",
            "visual_presets": {"background": "background"},
        }
    )
    options = {
        **story_t2i(settings, story),
        "comfyui_profile": "advanced",
        "image_purpose": "background",
        "visual_target_type": "scene",
    }
    execute = AsyncMock(side_effect=ComfyRequestError(400, "model (UNETLoader)"))
    monkeypatch.setattr(ComfyClient, "execute", execute)
    monkeypatch.setattr("backend.engine.comfyui_client.validate_provider_url", lambda url: url)
    monkeypatch.setattr(
        comfyui_images,
        "prepare_prompt",
        AsyncMock(return_value={"positive": "A room", "negative": ""}),
    )
    with pytest.raises(ComfyRequestError) as caught:
        await generate_comfy_image("A room", options, "unused", "scene")
    for message in (str(caught.value), diagnose_provider_error(caught.value, provider="comfyui")):
        assert "Anima backgrounds" in message
        assert "Background workflow" in message
        assert "background" in message
        assert "missing-anima.safetensors" in message
        assert "models/diffusion_models" in message
        assert "test preset" in message
        assert "https://example.com" not in message
        assert "A room" not in message
    assert execute.await_count == 1
    assert execute.call_args.args[0]["model"]["inputs"]["unet_name"] == "missing-anima.safetensors"
    assert settings["comfyui_assignments"]["background"] == "background"
