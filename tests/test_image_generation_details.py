"""Receipts match submitted ComfyUI inputs and exclude connection secrets."""

import json

import pytest

from backend.core.config import settings
from backend.engine.comfyui_images import generate_comfy_image
from tests.test_comfyui import comfy_options, fake_comfy, workflow

__all__ = ["comfy_options", "fake_comfy", "workflow"]


@pytest.mark.asyncio
async def test_details_match_submitted_graph(fake_comfy, comfy_options, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "DATA_DIR", str(tmp_path))
    graph = comfy_options["comfyui_profiles"]["simple"]["generate"]
    graph["graph"]["negative"] = {"class_type": "CLIPTextEncode", "inputs": {"text": "blur"}}
    graph["bindings"]["negative_prompt"] = {"node_id": "negative", "input_name": "text"}
    receipt = {}
    comfy_options.update(_generation_details=receipt, api_key="private-key", seed=42)

    async def prepared(*_args):
        return {"body": "cafe", "positive": "prefix, cafe, suffix", "negative": "blur, lettering"}

    monkeypatch.setattr("backend.engine.comfyui_images.prepare_prompt", prepared)
    await generate_comfy_image("original source", comfy_options, str(tmp_path), "moment.png")
    submitted = next(json.loads(r.content)["prompt"] for r in fake_comfy if r.url.path == "/prompt")
    assert receipt == {
        "provider": "comfyui",
        "workflow": "Example",
        "seed": 42,
        "positive_prompt": submitted["text"]["inputs"]["text"],
        "negative_prompt": submitted["negative"]["inputs"]["text"],
    }
    assert receipt["positive_prompt"] == "prefix, cafe, suffix"
    assert "private-key" not in json.dumps(receipt)
    assert "comfyui_url" not in receipt
