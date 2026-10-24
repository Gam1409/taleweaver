"""Portrait composition and opt-in references, with image providers mocked."""

import json
from copy import deepcopy

import pytest
from sqlalchemy import select

from backend.core import prompts
from backend.core.config import settings
from backend.engine.image_prompt_adapter import asset_source
from backend.models.user import User
from tests.conftest import TestSessionLocal
from tests.test_session_portraits import OLD_IMAGE, finish_job, portrait_world, start_job, workflow

__all__ = ["portrait_world", "workflow"]


@pytest.mark.parametrize("adapt", [True, False])
def test_comfy_portrait_composition_survives_template_adaptation(workflow, adapt):
    options = {
        "advanced_model_provider": "comfyui",
        "comfyui_presets": {
            "art": {"name": "Art", "generate": workflow, "prompt_rules": {"adapt_with_llm": adapt}}
        },
        "comfyui_assignments": {"advanced": "art"},
    }
    for kind in ("npc", "protagonist"):
        source = asset_source(options, kind, "legacy", name="Lina", description="A sailor")
        assert "Exactly one subject" in source
        assert "chest-up" in source
        if adapt:
            assert json.loads(source)["asset_type"] == kind
    assert "Exactly one subject" not in asset_source(options, "scene", "legacy")
    assert "3:2" not in prompts.NPC_IMAGE_PROMPT_TEMPLATE


@pytest.mark.parametrize("use_reference", [True, False])
async def test_portrait_reference_is_opt_in(
    auth_client, portrait_world, workflow, monkeypatch, use_reference
):
    monkeypatch.setattr(settings, "ALLOW_PRIVATE_NETWORK_MODELS", True)
    reference = deepcopy(workflow)
    reference["graph"]["input"] = {"class_type": "LoadImage", "inputs": {"image": "old.png"}}
    reference["bindings"]["image"] = {"node_id": "input", "input_name": "image"}
    async with TestSessionLocal() as db:
        user = (await db.execute(select(User))).scalars().first()
        user.t2i_settings = {
            **user.t2i_settings,
            "advanced_model_provider": "comfyui",
            "comfyui_profiles": {"advanced": {"generate": workflow, "reference": reference}},
        }
        await db.commit()
    result = await finish_job(
        auth_client,
        await start_job(
            auth_client,
            payload={
                "target_id": "NPC_NEW",
                "use_previous_image": use_reference,
                "change_description": "A cautious smile",
            },
        ),
    )
    assert result["state"] == "succeeded", result
    request = portrait_world[0]
    assert request["provider_options"].get("reference_image_url") == (
        OLD_IMAGE if use_reference else None
    )
    assert "A cautious smile" in request["prompt"]
    assert "Exactly one subject" in request["prompt"]


async def test_unsupported_reference_does_not_silently_generate(auth_client, portrait_world):
    result = await finish_job(
        auth_client,
        await start_job(
            auth_client,
            payload={
                "target_id": "NPC_NEW",
                "use_previous_image": True,
            },
        ),
    )
    assert result["state"] == "failed"
    assert "ComfyUI" in result["message"]
    assert portrait_world == []


async def test_missing_reference_workflow_keeps_old_portrait(
    auth_client, portrait_world, workflow, monkeypatch
):
    monkeypatch.setattr(settings, "ALLOW_PRIVATE_NETWORK_MODELS", True)
    async with TestSessionLocal() as db:
        user = (await db.execute(select(User))).scalars().first()
        user.t2i_settings = {
            **user.t2i_settings,
            "advanced_model_provider": "comfyui",
            "comfyui_profiles": {"advanced": {"generate": workflow}},
        }
        await db.commit()
    result = await finish_job(
        auth_client,
        await start_job(
            auth_client,
            payload={
                "target_id": "NPC_NEW",
                "use_previous_image": True,
            },
        ),
    )
    assert result["state"] == "failed"
    assert "workflow" in result["message"]
    assert portrait_world == []
