"""A preset test must generate its visible example, with honest saved-config diagnostics."""

import json
from copy import deepcopy
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from backend.engine.media_engine import MediaEngine
from backend.models.user import User
from tests.conftest import TestSessionLocal
from tests.test_comfyui import fake_comfy, workflow

__all__ = ["fake_comfy", "workflow"]
pytestmark = pytest.mark.asyncio
EXAMPLE = "A traveler in a red coat stands beside a stone bridge at dawn."


def payload(workflow, **extra):
    return {
        "model": "",
        "provider": "comfyui",
        "image_purpose": "background",
        "comfyui_url": "https://test-server.example",
        "comfyui_presets": {"nova": {"name": "Nova Anima", "generate": workflow}},
        "comfyui_assignments": {"background": "nova"},
        **extra,
    }


async def test_test_image_uses_example_instead_of_builtin_scene(auth_client, workflow, monkeypatch):
    generate = AsyncMock(return_value="/data/test.png")
    monkeypatch.setattr(MediaEngine, "generate_image", generate)
    result = await auth_client.post(
        "/api/settings/test-vision", json=payload(workflow, test_prompt=EXAMPLE)
    )
    assert result.status_code == 200, result.text
    assert result.json()["status"] == "success"
    assert generate.call_args.kwargs["prompt"] == EXAMPLE


async def test_prepared_preview_body_is_reused_without_another_adapter_call(
    auth_client, workflow, monkeypatch
):
    generate = AsyncMock(return_value="/data/test.png")
    monkeypatch.setattr(MediaEngine, "generate_image", generate)
    body = "A lone red-coated traveler rests beside a stone bridge."
    result = await auth_client.post(
        "/api/settings/test-vision", json=payload(workflow, test_prompt=EXAMPLE, prepared_body=body)
    )
    assert result.status_code == 200
    assert generate.call_args.kwargs["prompt"] == body
    assert generate.call_args.kwargs["provider_options"]["_prompt_prepared"] is True
    assert result.json()["test_configuration"]["prompt_source"] == "preview"


@pytest.mark.parametrize("value", [" ", "x" * 12001], ids=["blank", "too-long"])
async def test_invalid_test_description_never_generates(auth_client, workflow, monkeypatch, value):
    generate = AsyncMock(return_value="/data/test.png")
    monkeypatch.setattr(MediaEngine, "generate_image", generate)
    result = await auth_client.post(
        "/api/settings/test-vision", json=payload(workflow, test_prompt=value)
    )
    assert result.status_code == 422
    generate.assert_not_called()


async def test_success_reports_tested_and_different_saved_files(auth_client, workflow, monkeypatch):
    draft = deepcopy(workflow)
    draft["graph"]["model"] = {
        "class_type": "UNETLoader",
        "inputs": {"unet_name": "installed-nova.safetensors"},
    }
    saved = deepcopy(draft)
    saved["graph"]["model"]["inputs"]["unet_name"] = "novaAnimeAM_v10.safetensors"
    async with TestSessionLocal() as db:
        user = await db.scalar(select(User).where(User.username == "test_user"))
        user.t2i_settings = payload(saved)
        await db.commit()
    monkeypatch.setattr(MediaEngine, "generate_image", AsyncMock(return_value="/data/test.png"))
    response = await auth_client.post(
        "/api/settings/test-vision", json=payload(draft, test_prompt=EXAMPLE)
    )
    assert response.status_code == 200
    data = response.json()
    report = data["test_configuration"]
    assert report["tested"]["models"][0]["file"] == "installed-nova.safetensors"
    assert report["saved"]["models"][0]["file"] == "novaAnimeAM_v10.safetensors"
    assert report["matches_saved"] is False
    assert "Save Visuals Settings" in data["message"]
    assert "test-server.example" not in data["message"]
    assert EXAMPLE not in data["message"]


async def test_matching_saved_configuration_is_identified(auth_client, workflow, monkeypatch):
    config = payload(workflow)
    async with TestSessionLocal() as db:
        user = await db.scalar(select(User).where(User.username == "test_user"))
        user.t2i_settings = config
        await db.commit()
    monkeypatch.setattr(MediaEngine, "generate_image", AsyncMock(return_value="/data/test.png"))
    response = await auth_client.post(
        "/api/settings/test-vision", json={**config, "test_prompt": EXAMPLE}
    )
    assert response.json()["test_configuration"]["matches_saved"] is True


async def test_profile_smoke_test_keeps_its_default_example(auth_client, workflow, monkeypatch):
    generate = AsyncMock(return_value="/data/test.png")
    monkeypatch.setattr(MediaEngine, "generate_image", generate)
    response = await auth_client.post("/api/settings/test-vision", json=payload(workflow))
    assert response.json()["status"] == "success"
    assert generate.call_args.kwargs["prompt"] == "An empty stone courtyard at dawn"


async def test_prepared_preview_reaches_comfy_graph_once_without_more_llm_calls(
    auth_client, workflow, fake_comfy, monkeypatch
):
    from backend.core.llm_router import GameMasterLLM

    model = AsyncMock(side_effect=AssertionError("A prepared preview must not call the LLM again"))
    monkeypatch.setattr(GameMasterLLM, "for_role", model)
    config = payload(workflow, test_prompt=EXAMPLE, prepared_body="A traveler beside a bridge.")
    config["comfyui_presets"]["nova"]["prompt_rules"] = {
        "adapt_with_llm": True,
        "prefix": "masterpiece",
        "suffix": "soft light",
    }
    response = await auth_client.post("/api/settings/test-vision", json=config)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "success", response.text
    posted = [request for request in fake_comfy if request.url.path == "/prompt"]
    assert len(posted) == 1
    actual = json.loads(posted[0].content)["prompt"]["text"]["inputs"]["text"]
    assert actual == "masterpiece A traveler beside a bridge. soft light"
    assert actual.count("masterpiece") == 1
    model.assert_not_called()
