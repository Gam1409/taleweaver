"""Combined checkpoints must work without a separate server VAE file or loader."""

import json

import pytest

from backend.core.comfyui_starters import model_choices, starter_workflow
from backend.core.config import settings
from backend.engine.comfyui_images import generate_comfy_image
from backend.engine.comfyui_validation import inspect_workflow
from tests.test_comfyui import fake_comfy
from tests.test_comfyui_output import png_bytes

__all__ = ["fake_comfy"]


@pytest.mark.parametrize("family", ["sdxl", "illustrious", "animagine4", "flux1"])
@pytest.mark.parametrize("reference", [False, True])
async def test_checkpoint_vae_needs_no_external_loader(
    family, reference, fake_comfy, monkeypatch, tmp_path
):
    monkeypatch.setattr(settings, "DATA_DIR", str(tmp_path))
    workflow = starter_workflow(family, reference)
    registry = {
        node["class_type"]: {"input": {"required": {}}, "output_node": True}
        for node in workflow.graph.values()
    }
    # Supply all actual input names; the server has no VAELoader and no VAE files.
    for node in workflow.graph.values():
        registry[node["class_type"]]["input"]["required"].update(
            {name: ["ANY"] for name in node["inputs"]}
        )
    checkpoint = workflow.graph["model"]["inputs"]["ckpt_name"]
    registry["CheckpointLoaderSimple"]["input"]["required"]["ckpt_name"] = [[checkpoint]]
    assert "VAELoader" not in registry
    assert inspect_workflow(workflow, registry)["compatible"]
    assert not any(
        choice["input_name"] == "vae_name" for choice in model_choices(workflow, registry)
    )
    profile = "reference" if reference else "generate"
    options = {
        "comfyui_profiles": {"simple": {profile: workflow.model_dump()}},
        "visual_target_type": "npc",
        "simple_min_long_edge": 1024,
    }
    if reference:
        (tmp_path / "previous.png").write_bytes(png_bytes((80, 100)))
        options["reference_image_url"] = "/data/previous.png"
    await generate_comfy_image("A traveler", options, str(tmp_path), "portrait")
    graph = json.loads(next(r.content for r in fake_comfy if r.url.path == "/prompt"))["prompt"]
    assert graph["decode"]["inputs"]["vae"] == ["model", 2]
    assert not any(node["class_type"] == "VAELoader" for node in graph.values())
    if reference:
        assert graph["encode"]["inputs"]["vae"] == ["model", 2]


def test_separate_vae_remains_required_for_split_anima_workflow():
    workflow = starter_workflow("anima")
    registry = {
        node["class_type"]: {"input": {}, "output_node": True} for node in workflow.graph.values()
    }
    registry["VAELoader"]["input"] = {"required": {"vae_name": [[]]}}
    result = inspect_workflow(workflow, registry)
    assert not result["compatible"]
    assert "vae.vae_name: selected value is not available on the server." in result["errors"]
