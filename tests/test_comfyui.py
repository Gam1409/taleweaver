"""ComfyUI contract tests using in-process HTTP fakes, never a GPU server."""

import asyncio
import copy
import io
import json
from types import SimpleNamespace

import httpx
import pytest
from PIL import Image
from pydantic import ValidationError

from backend.core.comfyui_config import ComfyWorkflow, select_workflow
from backend.core.config import settings
from backend.engine.comfyui_client import ComfyClient
from backend.engine.comfyui_images import generate_comfy_image, reference_png
from backend.engine.comfyui_validation import inspect_workflow
from backend.engine.image_profiles import advanced_for, validate_image_profiles
from backend.engine.media_engine import MediaEngine


@pytest.fixture
def workflow():
    return {
        "name": "Example",
        "graph": {
            "text": {
                "class_type": "CLIPTextEncode",
                "inputs": {"text": "original", "clip": ["model", 1]},
            },
            "model": {
                "class_type": "CheckpointLoaderSimple",
                "inputs": {"ckpt_name": "sdxl.safetensors"},
            },
            "noise": {"class_type": "KSampler", "inputs": {"seed": 123}},
            "save": {"class_type": "SaveImage", "inputs": {"images": ["noise", 0]}},
        },
        "bindings": {
            "prompt": {"node_id": "text", "input_name": "text"},
            "seed": {"node_id": "noise", "input_name": "seed"},
        },
        "output_node": "save",
    }


@pytest.fixture
def registry():
    return {
        "CLIPTextEncode": {"input": {"required": {"text": ["STRING"], "clip": ["CLIP"]}}},
        "CheckpointLoaderSimple": {"input": {"required": {"ckpt_name": [["sdxl.safetensors"]]}}},
        "KSampler": {"input": {"required": {"seed": ["INT"]}}},
        "SaveImage": {"input": {"required": {"images": ["IMAGE"]}}, "output_node": True},
    }


@pytest.fixture
def comfy_options(workflow):
    return {
        "comfyui_url": "http://127.0.0.1:8188",
        "comfyui_timeout": 30,
        "comfyui_profiles": {"simple": {"generate": workflow}},
        "simple_model_provider": "comfyui",
        "simple_model": "",
        "advanced_model_provider": "openai",
        "advanced_model": "unused",
        "provider": "comfyui",
        "image_format": "png",
    }


@pytest.fixture
def fake_comfy(monkeypatch):
    monkeypatch.setattr(settings, "ALLOW_PRIVATE_NETWORK_MODELS", True)
    calls = []
    buffer = io.BytesIO()
    Image.new("RGBA", (16, 16), (20, 30, 40, 100)).save(buffer, "PNG")

    def handler(request):
        calls.append(request)
        path = request.url.path
        if path == "/prompt":
            return httpx.Response(200, json={"prompt_id": "job-1"})
        if path == "/history/job-1":
            return httpx.Response(
                200,
                json={
                    "job-1": {
                        "status": {"status_str": "success"},
                        "outputs": {
                            "save": {
                                "images": [
                                    {"filename": "result.png", "subfolder": "", "type": "output"}
                                ]
                            }
                        },
                    }
                },
            )
        if path == "/view":
            return httpx.Response(200, content=buffer.getvalue())
        if path == "/upload/image":
            return httpx.Response(
                200, json={"name": "uploaded.png", "subfolder": "refs", "type": "input"}
            )
        return httpx.Response(404)

    def init(self, url):
        self.url = url.rstrip("/")
        self.http = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    monkeypatch.setattr(ComfyClient, "__init__", init)
    return calls


def test_render_preserves_graph_and_json_types(workflow):
    spec = ComfyWorkflow.model_validate(workflow)
    graph = spec.render({"prompt": 'Русский "портрет"\n日本語', "seed": 777})
    assert graph["text"]["inputs"]["text"] == 'Русский "портрет"\n日本語'
    assert graph["noise"]["inputs"]["seed"] == 777
    assert graph["text"]["inputs"]["clip"] == ["model", 1]
    assert spec.graph == workflow["graph"]


@pytest.mark.parametrize(
    "case", ["editor", "missing", "linked", "duplicate", "wrong_type", "output"]
)
def test_invalid_workflow_is_rejected(workflow, case):
    if case == "editor":
        workflow["graph"] = {"nodes": []}
    elif case == "missing":
        workflow["bindings"]["prompt"]["node_id"] = "absent"
    elif case == "linked":
        workflow["bindings"]["prompt"]["input_name"] = "clip"
    elif case == "duplicate":
        workflow["bindings"]["negative_prompt"] = workflow["bindings"]["prompt"]
    elif case == "wrong_type":
        workflow["bindings"]["seed"] = workflow["bindings"].pop("prompt")
    else:
        workflow["output_node"] = "absent"
    with pytest.raises(ValidationError):
        ComfyWorkflow.model_validate(workflow)


def test_registry_reports_nodes_models_and_changed_inputs(workflow, registry):
    spec = ComfyWorkflow.model_validate(workflow)
    assert inspect_workflow(spec, registry)["compatible"]
    del registry["KSampler"]
    registry["CheckpointLoaderSimple"]["input"]["required"]["ckpt_name"] = [["other.safetensors"]]
    registry["CLIPTextEncode"]["input"]["required"] = {"renamed": ["STRING"]}
    report = inspect_workflow(spec, registry)
    assert not report["compatible"]
    assert report["missing_node_types"] == ["KSampler"]
    assert any("ckpt_name" in error for error in report["errors"])
    assert any("binding" in error for error in report["errors"])


def test_registry_does_not_require_reference_to_be_uploaded_yet(workflow, registry):
    workflow["graph"]["image"] = {
        "class_type": "LoadImage",
        "inputs": {"image": "not-uploaded.png"},
    }
    workflow["bindings"]["image"] = {"node_id": "image", "input_name": "image"}
    registry["LoadImage"] = {"input": {"required": {"image": [["other.png"]]}}}
    assert inspect_workflow(ComfyWorkflow.model_validate(workflow), registry)["compatible"]


def test_actual_profile_is_validated_and_override_wins(comfy_options):
    comfy_options["scene_model_quality"] = "simple"
    validate_image_profiles(
        SimpleNamespace(t2i_settings=comfy_options, encrypted_api_keys={}), ["scene"]
    )
    assert not advanced_for(comfy_options, "scene")
    assert advanced_for(comfy_options, "scene", True)
    with pytest.raises(ValueError, match="No image"):
        select_workflow(comfy_options, reference=True)


@pytest.mark.asyncio
async def test_full_pipeline_saves_image_and_preserves_alpha(
    fake_comfy, comfy_options, tmp_path, monkeypatch
):
    monkeypatch.setattr(settings, "DATA_DIR", str(tmp_path))
    url = await generate_comfy_image("a portrait", comfy_options, str(tmp_path), "result.png")
    assert url == "/data/result.png"
    with Image.open(tmp_path / "result.png") as image:
        assert image.mode == "RGBA"
    with Image.open(tmp_path / "result_thumb.png") as image:
        assert image.mode == "RGBA"
    submitted = json.loads(next(r.content for r in fake_comfy if r.url.path == "/prompt"))
    assert submitted["prompt"]["text"]["inputs"]["text"] == "a portrait"
    assert isinstance(submitted["prompt"]["noise"]["inputs"]["seed"], int)


@pytest.mark.asyncio
async def test_reference_is_uploaded_and_bound(
    fake_comfy, comfy_options, workflow, tmp_path, monkeypatch
):
    monkeypatch.setattr(settings, "DATA_DIR", str(tmp_path))
    Image.new("RGB", (12, 10)).save(tmp_path / "previous.png")
    reference = copy.deepcopy(workflow)
    reference["graph"]["load"] = {"class_type": "LoadImage", "inputs": {"image": "old.png"}}
    reference["bindings"]["image"] = {"node_id": "load", "input_name": "image"}
    comfy_options["comfyui_profiles"]["simple"]["reference"] = reference
    comfy_options["reference_image_url"] = "/data/previous.png"
    await generate_comfy_image("changed coat", comfy_options, str(tmp_path), "new.png")
    submitted = json.loads(next(r.content for r in fake_comfy if r.url.path == "/prompt"))
    assert submitted["prompt"]["load"]["inputs"]["image"] == "refs/uploaded.png"
    assert next(r for r in fake_comfy if r.url.path == "/upload/image")
    assert (tmp_path / "previous.png").exists()


@pytest.mark.parametrize(
    "url", ["https://example.com/image.png", "/data/missing.png", "/data/../outside.png"]
)
def test_reference_rejects_external_missing_and_escaping_paths(tmp_path, monkeypatch, url):
    monkeypatch.setattr(settings, "DATA_DIR", str(tmp_path))
    with pytest.raises(ValueError):
        reference_png(url)


@pytest.mark.parametrize(
    "entry", [{"status": {"status_str": "error"}}, {"outputs": {"different": {"images": []}}}]
)
def test_failed_or_wrong_output_is_not_success(entry):
    with pytest.raises(ValueError):
        ComfyClient._image_output(entry, "save")


@pytest.mark.asyncio
async def test_cancel_deletes_only_own_pending_job(fake_comfy, workflow, monkeypatch):
    entered = asyncio.Event()

    async def blocked(*args):
        entered.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(ComfyClient, "_wait", blocked)
    async with ComfyClient("http://127.0.0.1:8188") as client:
        task = asyncio.create_task(client.execute(workflow["graph"], "save", 30))
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert not any(r.url.path == "/interrupt" for r in fake_comfy)
    deleted = json.loads(next(r.content for r in fake_comfy if r.url.path == "/queue"))
    assert deleted == {"delete": ["job-1"]}


@pytest.mark.asyncio
async def test_submission_failure_does_not_retry(fake_comfy, workflow):
    calls = []

    def reject(request):
        calls.append(request)
        return httpx.Response(
            400, json={"node_errors": {"model": {"class_type": "CheckpointLoaderSimple"}}}
        )

    async with ComfyClient("http://127.0.0.1:8188") as client:
        await client.http.aclose()
        client.http = httpx.AsyncClient(transport=httpx.MockTransport(reject))
        with pytest.raises(ValueError, match="CheckpointLoaderSimple"):
            await client.execute(workflow["graph"], "save", 30)
    assert len(calls) == 1 and calls[0].url.path == "/prompt"


@pytest.mark.asyncio
@pytest.mark.parametrize("error_type", [TimeoutError, httpx.ReadTimeout])
async def test_timeout_dequeues_own_job(fake_comfy, workflow, monkeypatch, error_type):
    async def timed_out(*args):
        raise error_type("Queue timeout")

    monkeypatch.setattr(ComfyClient, "_wait", timed_out)
    async with ComfyClient("http://127.0.0.1:8188") as client:
        with pytest.raises(error_type):
            await client.execute(workflow["graph"], "save", 30)
    assert any(r.url.path == "/queue" for r in fake_comfy)
    assert not any(r.url.path == "/interrupt" for r in fake_comfy)


@pytest.mark.asyncio
@pytest.mark.parametrize("model", [None, ""])
async def test_comfy_direct_generation_accepts_workflow_owned_model(
    fake_comfy, comfy_options, tmp_path, monkeypatch, model
):
    monkeypatch.setattr(settings, "DATA_DIR", str(tmp_path))
    result = await MediaEngine.generate_image(
        prompt="A portrait",
        model=model,
        api_key=None,
        provider="comfyui",
        provider_options=comfy_options,
        target_dir=str(tmp_path),
    )
    assert result and result.startswith("/data/")


@pytest.mark.asyncio
async def test_comfy_needs_workflow_not_model_or_key(
    fake_comfy, comfy_options, tmp_path, monkeypatch
):
    monkeypatch.setattr(settings, "DATA_DIR", str(tmp_path))
    result = await MediaEngine.generate_entity_image(
        "portrait",
        "adventure",
        "npc",
        "NPC",
        {"t2i_settings": comfy_options},
        {},
        use_advanced_model=False,
    )
    assert result and result.startswith("/data/adventures/library/adventure/entities/")


def _use_story_presets(comfy_options, monkeypatch):
    from unittest.mock import AsyncMock

    from backend.core.image_prompt_templates import template_rules
    from backend.core.llm_router import GameMasterLLM

    llm = SimpleNamespace(model="fake", aexecute_simple_task=AsyncMock(return_value="Visual facts"))
    monkeypatch.setattr(GameMasterLLM, "for_role", lambda *_args: llm)
    comfy_options["comfyui_presets"] = {}
    for role in ("simple", "advanced"):
        rules = template_rules("sdxl").model_dump()
        rules["prefix"] = f"{role}_trigger"
        comfy_options["comfyui_presets"][role] = {
            **comfy_options["comfyui_profiles"][role],
            "name": role,
            "prompt_rules": rules,
        }
        # Story choices must override these unrelated global providers.
        comfy_options[f"{role}_model_provider"] = "openai"
    return llm


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("edge", "expected_dimensions", "use_presets"),
    [
        (1024, [(1024, 512), (816, 1024), (1024, 576), (816, 1024), (1024, 1024)], False),
        (4096, [(2048, 1024), (1024, 1272), (1600, 896), (1024, 1272), (1024, 1024)], False),
        (1024, [(1024, 512), (816, 1024), (1024, 576), (816, 1024), (1024, 1024)], True),
    ],
)
async def test_manifest_generates_all_visuals_with_correct_profiles(
    fake_comfy, comfy_options, tmp_path, monkeypatch, edge, expected_dimensions, use_presets
):
    from sqlalchemy import select

    from backend.engine.manifest_apply.apply import apply_manifest
    from backend.models.adventure_template import AdventureTemplate
    from backend.models.avatar import Avatar
    from backend.models.user import User
    from backend.models.world_entity import WorldEntity, WorldScene
    from tests.conftest import TestSessionLocal

    monkeypatch.setattr(settings, "DATA_DIR", str(tmp_path))
    comfy_options["simple_min_long_edge"] = edge
    comfy_options["advanced_min_long_edge"] = edge
    base = comfy_options["comfyui_profiles"]["simple"]["generate"]
    base["graph"]["size"] = {
        "class_type": "EmptyLatentImage",
        "inputs": {"width": 64, "height": 64},
    }
    for dimension in ("width", "height"):
        base["bindings"][dimension] = {"node_id": "size", "input_name": dimension}
    advanced = copy.deepcopy(comfy_options["comfyui_profiles"]["simple"])
    advanced["generate"]["graph"]["model"]["inputs"]["ckpt_name"] = "advanced.safetensors"
    comfy_options["comfyui_profiles"]["advanced"] = advanced
    comfy_options["advanced_model_provider"] = "comfyui"
    comfy_options["scene_model_quality"] = "simple"
    selections = {"simple": "simple", "advanced": "advanced"} if use_presets else {}
    llm = _use_story_presets(comfy_options, monkeypatch) if use_presets else None
    manifest = {
        "teaser": "A harbour",
        "plot": "Find the key",
        "language": "English",
        "protagonist": {"name": "Sailor", "role": "Explorer", "description": "Red coat"},
        "scenes": [{"id": "DOCK", "name": "Dock", "description": "A wooden pier"}],
        "npcs": [
            {"id": "KEEPER", "name": "Keeper", "description": "A grey cloak", "scene_id": "DOCK"}
        ],
        "objects": [
            {
                "id": "KEY",
                "name": "Key",
                "description": "An iron key",
                "scene_id": "DOCK",
                "item_type": "KEY",
            }
        ],
    }
    async with TestSessionLocal() as db:
        user = User(username="comfy-world", hashed_password="unused", t2i_settings=comfy_options)
        db.add(user)
        await db.flush()
        adventure = AdventureTemplate(
            title="Harbour",
            original_prompt="A harbour",
            owner_id=user.id,
            original_manifest={"visual_presets": selections},
        )
        db.add(adventure)
        await db.commit()
        await apply_manifest(
            db,
            adventure.id,
            manifest,
            user=user,
            gen_npc=True,
            gen_items=True,
            gen_scenes=True,
            gen_protagonist_image=True,
        )
        assert adventure.image_url and not adventure.creation_error
        avatar = (await db.execute(select(Avatar))).scalars().first()
        assert avatar.profile_image
        scene = (await db.execute(select(WorldScene))).scalars().first()
        assert scene.image_url
        entities = (await db.execute(select(WorldEntity))).scalars().all()
        assert len(entities) == 2 and all(entity.image_url for entity in entities)
        assert adventure.original_manifest["visual_presets"] == selections
    graphs = [json.loads(r.content)["prompt"] for r in fake_comfy if r.url.path == "/prompt"]
    assert len(graphs) == 5
    checkpoints = [graph["model"]["inputs"]["ckpt_name"] for graph in graphs]
    assert checkpoints == [
        "advanced.safetensors",
        "advanced.safetensors",
        "sdxl.safetensors",
        "advanced.safetensors",
        "sdxl.safetensors",
    ]

    dimensions = [(g["size"]["inputs"]["width"], g["size"]["inputs"]["height"]) for g in graphs]
    assert dimensions == expected_dimensions
    if use_presets:
        assert llm.aexecute_simple_task.await_count == 5
        assert [g["text"]["inputs"]["text"] for g in graphs] == [
            f"{role}_trigger Visual facts"
            for role in ("advanced", "advanced", "simple", "advanced", "simple")
        ]
