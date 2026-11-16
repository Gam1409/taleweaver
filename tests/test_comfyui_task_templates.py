"""Task coverage, component wiring, limits and API persistence for bundled recipes."""

import itertools
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from backend.core.comfyui_config import ComfyPreset
from backend.core.comfyui_starter_models import FAMILIES, LoaderRecipe
from backend.core.comfyui_starters import starter_workflow
from backend.core.comfyui_task_templates import TASKS, preset_catalog, task_preset
from backend.core.image_prompt_templates import TEMPLATES, template_rules
from backend.core.image_purposes import PURPOSES, purpose_target
from backend.core.visual_limits import visual_limits
from backend.engine.comfyui_output import bounded_dimensions
from backend.models.user import User
from tests.conftest import TestSessionLocal

# Socket counts from upstream core loader/conditioning schemas, not the recipe generator.
OUTPUTS = {
    "CheckpointLoaderSimple": 3,
    "UNETLoader": 1,
    "CLIPLoader": 1,
    "DualCLIPLoader": 1,
    "TripleCLIPLoader": 1,
    "VAELoader": 1,
    "CLIPTextEncode": 1,
    "CLIPTextEncodeFlux": 1,
    "ConditioningZeroOut": 1,
    "PrimitiveStringMultiline": 1,
    "EmptyLatentImage": 1,
    "EmptySD3LatentImage": 1,
    "KSampler": 1,
    "VAEDecode": 1,
    "SaveImage": 0,
    "ModelSamplingAuraFlow": 1,
    "LoadImage": 2,
    "ImageScale": 1,
    "VAEEncode": 1,
}


def check_links(graph):
    for entry in graph.values():
        assert entry["class_type"] in OUTPUTS
        for value in entry["inputs"].values():
            if isinstance(value, list):
                assert len(value) == 2 and value[0] in graph
                assert 0 <= value[1] < OUTPUTS[graph[value[0]]["class_type"]]


def test_catalog_covers_all_tasks_and_concrete_prompt_families():
    assert set(FAMILIES) == {item["id"] for item in TEMPLATES} - {"natural"}
    assert set(TASKS) == PURPOSES
    catalog = preset_catalog()
    assert len(catalog) == 80
    assert len({item["id"] for item in catalog}) == 80
    assert all("generate" not in item for item in catalog)  # Graphs are fetched on demand.


@pytest.mark.parametrize(("family", "purpose"), list(itertools.product(FAMILIES, TASKS)))
def test_each_task_preset_is_bound_and_sized_for_its_target(family, purpose):
    result = task_preset(family, purpose)
    preset = ComfyPreset.model_validate(result["preset"])
    assert preset.purpose_tags == [purpose]
    assert preset.name.startswith(TASKS[purpose][0] + " · ")
    assert FAMILIES[family]["name"] in preset.name
    assert "No reference" in preset.generate.name
    if preset.reference:
        assert "With reference (img2img)" in preset.reference.name
    assert len(preset.generate.name) <= 120
    assert preset.prompt_rules.template_id == family
    assert "Task composition:" in preset.prompt_rules.instructions
    assert preset.mature_themes is False
    assert bool(preset.reference) == (purpose not in ("avatar", "catalog"))
    for workflow in (preset.generate, preset.reference):
        if workflow is None:
            continue
        check_links(workflow.graph)
        limits = visual_limits(purpose_target(purpose))
        for key, bound in (("width", "maxWidth"), ("height", "maxHeight")):
            binding = workflow.bindings[key]
            value = workflow.graph[binding.node_id]["inputs"][binding.input_name]
            assert 0 < value <= limits[bound]
            assert value % workflow.dimension_multiple == 0
        prompt = workflow.bindings["prompt"]
        assert workflow.graph[prompt.node_id]["inputs"][prompt.input_name]
        dims = bounded_dimensions(
            {"visual_target_type": purpose_target(purpose), "width": 4096, "height": 4096},
            workflow.dimension_multiple,
        )
        assert dims["width"] <= limits["maxWidth"] and dims["height"] <= limits["maxHeight"]


@pytest.mark.parametrize("family", FAMILIES)
@pytest.mark.parametrize(
    ("encoder", "vae"), list(itertools.product(("embedded", "external"), repeat=2))
)
def test_checkpoint_components_are_independent_and_never_double_wired(family, encoder, vae):
    recipe = LoaderRecipe(
        layout="checkpoint",
        encoder_source=encoder,
        vae_source=vae,
        checkpoint_name="custom-combined.safetensors",
    )
    workflow = starter_workflow(family, reference=True, recipe=recipe)
    graph = workflow.graph
    check_links(graph)
    assert graph["model"]["class_type"] == "CheckpointLoaderSimple"
    assert graph["positive"]["inputs"]["clip"] == (
        ["model", 1] if encoder == "embedded" else ["clip", 0]
    )
    assert graph["decode"]["inputs"]["vae"] == (["model", 2] if vae == "embedded" else ["vae", 0])
    assert graph["encode"]["inputs"]["vae"] == graph["decode"]["inputs"]["vae"]
    assert ("clip" in graph) == (encoder == "external")
    assert ("vae" in graph) == (vae == "external")


def test_sd35_standard_and_aio_use_different_checkpoint_contents():
    standard = starter_workflow("sd35").graph
    aio = starter_workflow("sd35", recipe=LoaderRecipe(encoder_source="embedded")).graph
    assert standard["clip"]["class_type"] == "TripleCLIPLoader"
    assert standard["decode"]["inputs"]["vae"] == ["model", 2]
    assert "clip" not in aio and "vae" not in aio
    assert standard["model"]["inputs"]["ckpt_name"] != aio["model"]["inputs"]["ckpt_name"]
    assert aio["latent"]["class_type"] == "EmptySD3LatentImage"


def test_qwen_and_nova_follow_their_native_architectures():
    qwen = starter_workflow("qwen_image").graph
    nova = starter_workflow("nova_anime_am").graph
    assert qwen["clip"]["inputs"]["type"] == "qwen_image"
    assert qwen["sampling"]["class_type"] == "ModelSamplingAuraFlow"
    assert qwen["sampler"]["inputs"]["model"] == ["sampling", 0]
    assert nova["clip"]["inputs"]["clip_name"] == "qwen_3_06b_base.safetensors"
    assert nova["latent"]["class_type"] == "EmptyLatentImage"


@pytest.mark.parametrize("family", ["flux1", "anima", "nova_anime_am", "qwen_image"])
def test_diffusion_only_requires_external_components(family):
    workflow = starter_workflow(family, recipe=LoaderRecipe(layout="diffusion"))
    assert workflow.graph["model"]["class_type"] == "UNETLoader"
    assert "clip" in workflow.graph and "vae" in workflow.graph
    with pytest.raises(ValueError, match="diffusion-only"):
        starter_workflow(family, recipe=LoaderRecipe(layout="diffusion", vae_source="embedded"))


def test_unknown_and_unverified_packaging_fail_visibly():
    with pytest.raises(ValueError, match="Unknown"):
        task_preset("natural", "npc")
    with pytest.raises(ValueError, match="filename"):
        task_preset(
            "anima",
            "npc",
            LoaderRecipe(layout="checkpoint", encoder_source="embedded", vae_source="embedded"),
        )
    with pytest.raises(ValueError, match="custom split"):
        starter_workflow("sdxl", recipe=LoaderRecipe(layout="diffusion"))


@pytest.mark.asyncio
async def test_task_template_api_and_settings_roundtrip(auth_client, monkeypatch):
    from backend.api.routes import config_api
    from backend.core.config import settings

    monkeypatch.setattr(settings, "ALLOW_PRIVATE_NETWORK_MODELS", True)
    monkeypatch.setattr(config_api, "_fetch_ollama_models", AsyncMock(return_value=[]))
    catalog = await auth_client.get("/api/settings/comfyui/starter-presets")
    assert catalog.status_code == 200 and len(catalog.json()) == 80
    response = await auth_client.post(
        "/api/settings/comfyui/starter-presets",
        json={"family": "sd35", "purpose": "background", "encoder_source": "embedded"},
    )
    assert response.status_code == 200, response.text
    preset = response.json()["preset"]
    payload = {
        "simple_model": "",
        "advanced_model": "",
        "provider": "openai",
        "simple_model_provider": "openai",
        "advanced_model_provider": "openai",
        "comfyui_presets": {"background": preset},
        "comfyui_assignments": {"background": "background"},
    }
    saved = await auth_client.post("/api/settings/t2i", json=payload)
    assert saved.status_code == 200, saved.text
    loaded = (await auth_client.get("/api/settings?include_available_constants=false")).json()
    assert loaded["t2i_settings"]["comfyui_presets"]["background"] == preset
    invalid = await auth_client.post(
        "/api/settings/comfyui/starter-presets",
        json={"family": "qwen_image", "purpose": "cover", "vae_source": "embedded"},
    )
    assert invalid.status_code == 400
    async with TestSessionLocal() as db:
        user = (await db.execute(select(User))).scalars().first()
        user.role = "user"
        await db.commit()
    assert (await auth_client.get("/api/settings/comfyui/starter-presets")).status_code == 403
    assert (
        await auth_client.post(
            "/api/settings/comfyui/starter-presets", json={"family": "sdxl", "purpose": "npc"}
        )
    ).status_code == 403


def test_workflow_names_distinguish_packaging_and_purpose():
    standard = task_preset("sd35", "npc")["preset"]
    aio = task_preset("sd35", "npc", LoaderRecipe(encoder_source="embedded"))["preset"]
    cover = task_preset("sd35", "cover", LoaderRecipe(encoder_source="embedded"))["preset"]
    assert (
        standard["generate"]["name"]
        == "NPC portrait · SD3.5 Large · No reference · External encoders"
    )
    assert aio["generate"]["name"] == "NPC portrait · SD3.5 Large · No reference · AIO"
    assert cover["generate"]["name"].startswith("Adventure cover · ")
    assert aio["reference"]["name"] == "NPC portrait · SD3.5 Large · With reference (img2img) · AIO"


@pytest.mark.parametrize("family", FAMILIES)
async def test_npc_and_hero_framing_survives_prompt_preparation(family):
    from backend.engine.image_prompt_adapter import prepare_prompt

    for purpose in ("npc", "protagonist"):
        preset = task_preset(family, purpose)["preset"]
        options = {
            "comfyui_presets": {"portrait": preset},
            "comfyui_assignments": {purpose: "portrait"},
            "image_purpose": purpose,
            "_prompt_prepared": True,
        }
        source = "One character in a green jacket."
        prepared = await prepare_prompt(source, options)
        assert source in prepared["positive"]
        normalized = prepared["positive"].lower().replace("-", " ")
        assert "waist up" in normalized
        assert "entire head visible" in normalized
        assert "crop at" in normalized
        # FLUX deliberately has no negative binding; other families receive the crop exclusions.
        if "negative_prompt" in preset["generate"]["bindings"]:
            assert "full body" in prepared["negative"]
        assert "waist" not in template_rules(family).instructions.lower()
