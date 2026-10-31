"""Preset routing and model-specific prompt assembly; external services are mocked."""

import asyncio
import copy
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from backend.core.comfyui_config import ComfyPreset, select_profile, select_workflow
from backend.core.comfyui_presets import normalize_comfy_presets
from backend.core.config import settings
from backend.core.image_model_detection import detect_preset_template, detect_template
from backend.core.image_prompt_rules import ImagePromptRules
from backend.core.image_prompt_templates import TEMPLATES, template_rules
from backend.core.llm_router import GameMasterLLM
from backend.engine.image_prompt_adapter import prepare_prompt
from backend.engine.media_engine import MediaEngine
from backend.engine.story_visual_presets import story_t2i
from backend.models.adventure_template import AdventureTemplate
from backend.models.user import User
from tests.conftest import TestSessionLocal
from tests.test_adventures_api import _create_adventure
from tests.test_comfyui import comfy_options, fake_comfy, workflow

__all__ = ["comfy_options", "fake_comfy", "workflow"]


@pytest.fixture(autouse=True)
def no_model_discovery(monkeypatch):
    from backend.api.routes import config_api

    monkeypatch.setattr(config_api, "_fetch_ollama_models", AsyncMock(return_value=[]))
    monkeypatch.setattr(
        "backend.api.routes.adventures.editing.auto_fix.run_auto_fix_pass_safely",
        AsyncMock(return_value=None),
    )


def named_preset(workflow, *, template="sdxl", automatic=False):
    return {
        "name": "Illustrations",
        "generate": copy.deepcopy(workflow),
        "reference": None,
        "prompt_rules": template_rules(template).model_dump(),
        "auto_prompt_template": automatic,
    }


def preset_options(comfy_options, workflow, **kwargs):
    result = copy.deepcopy(comfy_options)
    result["comfyui_presets"] = {"art": named_preset(workflow, **kwargs)}
    result["comfyui_assignments"] = {"simple": "art"}
    return result


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("models/animagine-xl-4.0-opt.safetensors", "animagine4"),
        ("models/novaAnimeAM_v6029B.safetensors", "anima"),
        ("models/novaAnimeXL_ilV190.safetensors", None),
        ("ponyDiffusionV6XL_v6StartWithThisOne.safetensors", "pony6"),
        ("illustriousXL_v01.safetensors", "illustrious"),
        ("flux1-dev-Q6_K.gguf", "flux1"),
        ("sd3.5_large.safetensors", "sd35"),
        ("qwen_image_fp8.safetensors", "qwen_image"),
        ("v1-5-pruned-emaonly.safetensors", "sd15"),
        ("sd_xl_base_1.0.safetensors", "sdxl"),
        ("model.safetensors", None),
        ("flux1-kontext-dev.safetensors", None),
        ("qwen-image-edit-2509.safetensors", None),
        ("animagine-xl-3.1.safetensors", None),
        ("flux2-dev.safetensors", None),
    ],
)
def test_filename_detection_is_conservative(workflow, name, expected):
    workflow["graph"]["model"]["inputs"]["ckpt_name"] = name
    assert detect_template(workflow["graph"])["template_id"] == expected


def test_lora_names_do_not_choose_base_template_and_ambiguous_models_stop(workflow):
    graph = workflow["graph"]
    graph["model"]["inputs"]["ckpt_name"] = "sd_xl_base_1.0.safetensors"
    graph["lora"] = {"class_type": "LoraLoader", "inputs": {"lora_name": "ponyV6.safetensors"}}
    assert detect_template(graph)["template_id"] == "sdxl"
    graph["other"] = {"class_type": "UNETLoader", "inputs": {"unet_name": "flux1-dev.safetensors"}}
    assert detect_template(graph)["template_id"] is None


def test_manual_rules_survive_checkpoint_changes(workflow):
    preset = named_preset(workflow, template="pony6")
    preset["prompt_rules"]["prefix"] = "my_trigger"
    preset["generate"]["graph"]["model"]["inputs"]["ckpt_name"] = "flux1-dev.safetensors"
    assert ComfyPreset.model_validate(preset).prompt_rules.prefix == "my_trigger"
    preset["auto_prompt_template"] = True
    assert ComfyPreset.model_validate(preset).prompt_rules.template_id == "flux1"


def test_reference_workflow_must_match_for_automatic_rules(workflow):
    graph = workflow["graph"]
    graph["model"]["inputs"]["ckpt_name"] = "sd_xl_base_1.0.safetensors"
    other = copy.deepcopy(graph)
    assert detect_preset_template(graph, other)["template_id"] == "sdxl"
    other["model"]["inputs"]["ckpt_name"] = "qwen-image-edit.safetensors"
    assert detect_preset_template(graph, other)["template_id"] is None


def test_uncertain_automatic_detection_does_not_run_old_rules(comfy_options, workflow):
    options = preset_options(comfy_options, workflow, automatic=True)
    with pytest.raises(ValueError, match="uncertain"):
        select_workflow(options)


def test_legacy_upgrade_is_lossless_and_idempotent(comfy_options):
    original = copy.deepcopy(comfy_options)
    migrated = normalize_comfy_presets(original)
    assert normalize_comfy_presets(migrated) == migrated
    assert original == comfy_options
    assert migrated["comfyui_presets"]["legacy-simple"]["prompt_rules"] is None
    assert select_workflow(migrated).graph == select_workflow(original).graph


def test_all_templates_are_typed_and_do_not_contain_workflow_controls():
    for template in TEMPLATES:
        assert ImagePromptRules.model_validate(template["rules"])
        assert not {"cfg", "steps", "strength_model", "denoise"} & template["rules"].keys()


@pytest.mark.asyncio
async def test_adapter_receives_policy_and_keeps_triggers_outside_llm(
    comfy_options, workflow, monkeypatch
):
    options = preset_options(comfy_options, workflow, template="pony6")
    options["_prompt_user"] = object()
    rules = options["comfyui_presets"]["art"]["prompt_rules"]
    rules["prefix"] += ", my_character_trigger"
    llm = SimpleNamespace(
        model="fake", aexecute_simple_task=AsyncMock(return_value="solo, red coat, lantern")
    )
    calls = []

    def for_role(user, role):
        calls.append(role)
        return llm

    monkeypatch.setattr(GameMasterLLM, "for_role", for_role)
    result = await prepare_prompt("A traveler with a lantern.", options)
    assert calls == ["small"]
    assert (
        result["positive"]
        == "score_9, score_8_up, score_7_up, my_character_trigger, solo, red coat, lantern"
    )
    system = llm.aexecute_simple_task.call_args.kwargs["system_prompt"]
    assert '"format": "tags"' in system and '"language": "English"' in system
    assert "my_character_trigger" not in system


@pytest.mark.asyncio
async def test_manual_body_skips_llm_and_preserves_workflow_negative(
    comfy_options, workflow, monkeypatch
):
    workflow["graph"]["neg"] = {"class_type": "CLIPTextEncode", "inputs": {"text": "bad hands"}}
    workflow["bindings"]["negative_prompt"] = {"node_id": "neg", "input_name": "text"}
    options = preset_options(comfy_options, workflow)
    options["_prompt_prepared"] = True
    llm = AsyncMock(side_effect=AssertionError("Manual text must not invoke the adapter"))
    monkeypatch.setattr(GameMasterLLM, "for_role", llm)
    result = await prepare_prompt("Exactly my wording", options)
    assert result["positive"] == "Exactly my wording"
    assert result["negative"].startswith("bad hands, text, watermark")
    assert not llm.called


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled", [False, True])
async def test_suggestion_uses_manual_profile_and_body_is_not_adapted_twice(
    comfy_options, workflow, monkeypatch, enabled
):
    from backend.api.routes.adventures.schemas import SuggestPromptRequest
    from backend.core import mature_content_prompts
    from backend.engine.preset_prompt_suggestion import suggest_preset_prompt

    marker = "TEST CONTENT PROFILE ADDENDUM"
    monkeypatch.setattr(mature_content_prompts, "image_prompt_addendum", lambda level: marker)

    options = preset_options(comfy_options, workflow, template="pony6")
    options["comfyui_presets"]["detailed"] = named_preset(workflow, template="flux1")
    options["comfyui_presets"]["art"]["mature_themes"] = enabled
    options["comfyui_presets"]["detailed"]["mature_themes"] = not enabled
    story = SimpleNamespace(
        original_manifest={
            "visual_presets": {"advanced": "detailed"},
            "nsfw_settings": {"enabled": enabled, "level": "hard"},
        },
        selected_image_styles=[],
        selected_tone=None,
    )
    user = SimpleNamespace(t2i_settings=options, image_styles_catalog=[], tone_catalog=[])
    llm = SimpleNamespace(model="fake", aexecute_simple_task=AsyncMock(return_value="red coat"))
    monkeypatch.setattr(GameMasterLLM, "for_role", lambda *_args: llm)
    payload = SuggestPromptRequest(target_type="npc", target_id="npc", use_advanced_model=False)
    body = await suggest_preset_prompt(user, story, payload, "Traveler", "A red coat")
    assert body == "red coat" and "score_9" not in body
    assert '"format": "tags"' in llm.aexecute_simple_task.call_args.kwargs["system_prompt"]
    system = llm.aexecute_simple_task.call_args.kwargs["system_prompt"]
    assert (marker in system) is enabled
    prepared = await prepare_prompt(body, {**options, "_prompt_prepared": True})
    assert prepared["positive"] == "score_9, score_8_up, score_7_up, red coat"
    assert llm.aexecute_simple_task.await_count == 1
    payload.use_advanced_model = True
    await suggest_preset_prompt(user, story, payload, "Traveler", "A red coat")
    assert '"format": "description"' in llm.aexecute_simple_task.call_args.kwargs["system_prompt"]
    system = llm.aexecute_simple_task.call_args.kwargs["system_prompt"]
    # The advanced profile has the opposite flag, so both gates are never on.
    assert marker not in system


@pytest.mark.asyncio
async def test_prompt_timeout_does_not_submit_image_job(
    fake_comfy, comfy_options, workflow, monkeypatch
):
    from backend.engine import image_prompt_adapter
    from backend.engine.comfyui_images import generate_comfy_image

    async def slow(**_kwargs):
        await asyncio.Event().wait()

    llm = SimpleNamespace(model="fake", aexecute_simple_task=slow)
    monkeypatch.setattr(GameMasterLLM, "for_role", lambda *_args: llm)
    monkeypatch.setattr(image_prompt_adapter, "role_timeout", lambda user, role: 0.01)
    options = preset_options(comfy_options, workflow)
    options["_prompt_user"] = object()
    with pytest.raises(asyncio.TimeoutError, match="Small/Utility LLM image-prompt preparation"):
        await generate_comfy_image("A traveler", options, "unused", "unused")
    assert not fake_comfy


@pytest.mark.asyncio
async def test_generation_uses_llm_result_and_leaves_sampler_unchanged(
    fake_comfy, comfy_options, workflow, tmp_path, monkeypatch
):
    monkeypatch.setattr(settings, "DATA_DIR", str(tmp_path))
    workflow["graph"]["noise"]["inputs"].update({"cfg": 5.5, "steps": 23})
    options = preset_options(comfy_options, workflow, template="animagine4")
    llm = SimpleNamespace(
        model="fake", aexecute_simple_task=AsyncMock(return_value="solo, traveler, red coat")
    )
    monkeypatch.setattr(GameMasterLLM, "for_role", lambda *_args: llm)
    url = await MediaEngine.generate_entity_image(
        "Traveler in red",
        "story",
        "traveler",
        "NPC",
        {"t2i_settings": options, "prompt_user": object()},
        {},
    )
    assert url
    graph = json.loads(next(r.content for r in fake_comfy if r.url.path == "/prompt"))["prompt"]
    assert (
        graph["text"]["inputs"]["text"]
        == "solo, traveler, red coat, masterpiece, high score, great score, absurdres"
    )
    assert graph["noise"]["inputs"]["cfg"] == 5.5
    assert graph["noise"]["inputs"]["steps"] == 23
    assert llm.aexecute_simple_task.await_count == 1


def test_story_override_uses_named_preset_without_mutating_global_settings(comfy_options, workflow):
    options = preset_options(comfy_options, workflow)
    saved = copy.deepcopy(options)
    story = SimpleNamespace(original_manifest={"visual_presets": {"advanced": "art"}})
    resolved = story_t2i(options, story)
    assert resolved["advanced_model_provider"] == "comfyui"
    assert select_profile({**resolved, "comfyui_profile": "advanced"}).name == "Illustrations"
    assert options == saved
    story.original_manifest["visual_presets"]["advanced"] = "unavailable"
    with pytest.raises(ValueError, match="unavailable"):
        story_t2i(options, story)


@pytest.mark.asyncio
async def test_settings_preview_and_story_selection_roundtrip(
    auth_client, comfy_options, workflow, monkeypatch
):
    monkeypatch.setattr(settings, "ALLOW_PRIVATE_NETWORK_MODELS", True)
    options = preset_options(comfy_options, workflow)
    options["comfyui_presets"]["art"]["prompt_rules"]["adapt_with_llm"] = False
    response = await auth_client.post("/api/settings/t2i", json=options)
    assert response.status_code == 200, response.text
    loaded = (await auth_client.get("/api/settings")).json()["t2i_settings"]
    assert loaded["comfyui_assignments"]["simple"] == "art"
    templates = await auth_client.get("/api/settings/comfyui/prompt-templates")
    assert templates.status_code == 200 and len(templates.json()) >= 9
    preview = await auth_client.post(
        "/api/settings/comfyui/preview-prompt",
        json={"preset": options["comfyui_presets"]["art"], "description": "A lantern"},
    )
    assert preview.status_code == 200 and preview.json()["positive"] == "A lantern"
    ids = await _create_adventure(auth_client, "Preset story")
    path = f"/api/adventures/{ids['adventure_id']}/visual-presets"
    saved = await auth_client.put(path, json={"selection": {"advanced": "art"}})
    assert saved.status_code == 200, saved.text
    assert (await auth_client.get(path)).json()["selection"] == {"advanced": "art"}
    invalid = await auth_client.put(path, json={"selection": {"advanced": "missing"}})
    assert invalid.status_code == 400
    assert (await auth_client.get(path)).json()["selection"] == {"advanced": "art"}
    duplicate = await auth_client.post(
        f"/api/adventures/{ids['adventure_id']}/duplicate", json={"title": "Preset copy"}
    )
    assert duplicate.status_code == 201, duplicate.text
    duplicate_path = f"/api/adventures/{duplicate.json()['id']}/visual-presets"
    assert (await auth_client.get(duplicate_path)).json()["selection"] == {"advanced": "art"}
    async with TestSessionLocal() as db:
        from backend.engine.adventure_exporter import AdventureExporter
        from backend.engine.adventure_importer import AdventureTemplateImporter

        manifest = await AdventureExporter.build_full_manifest(db, ids["adventure_id"])
        if isinstance(manifest, str):
            manifest = json.loads(manifest)
        assert manifest["visual_presets"] == {"advanced": "art"}
        assert "comfyui_presets" not in manifest
        manifest["adventure"]["title"] = "Imported preset story"
        user = (await db.execute(select(User))).scalars().first()
        assert await AdventureTemplateImporter.import_adv_manifest(
            db, manifest, owner_id=user.id, allow_session=False
        )
        imported = (
            await db.execute(
                select(AdventureTemplate).where(AdventureTemplate.title == "Imported preset story")
            )
        ).scalar_one()
        assert imported.original_manifest["visual_presets"] == {"advanced": "art"}


@pytest.mark.asyncio
async def test_story_selection_checks_ownership(auth_client):
    ids = await _create_adventure(auth_client, "Owned presets")
    async with TestSessionLocal() as db:
        adventure = await db.get(AdventureTemplate, ids["adventure_id"])
        adventure.owner_id = None
        await db.commit()
    path = f"/api/adventures/{ids['adventure_id']}/visual-presets"
    assert (await auth_client.get(path)).status_code == 404
    assert (await auth_client.put(path, json={"selection": {}})).status_code == 404


@pytest.mark.asyncio
async def test_prompt_tools_are_admin_only(auth_client):
    async with TestSessionLocal() as db:
        user = (await db.execute(select(User))).scalars().first()
        user.role = "user"
        await db.commit()
    assert (await auth_client.get("/api/settings/comfyui/prompt-templates")).status_code == 403
    assert (
        await auth_client.post("/api/settings/comfyui/detect-template", json={"graph": {}})
    ).status_code == 403
