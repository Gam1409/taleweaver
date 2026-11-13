"""Neutral image policies with distinct task and legacy quality assignments."""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from backend.core.comfyui_config import prompt_rules
from backend.core.image_purposes import purpose_for
from backend.core.llm_router import GameMasterLLM
from backend.engine.image_profiles import advanced_for
from backend.engine.story_visual_presets import story_t2i


@pytest.fixture(autouse=True)
def no_live_prompt_models(monkeypatch):
    for name in ("__init__", "for_role"):
        monkeypatch.setattr(
            GameMasterLLM, name, Mock(side_effect=AssertionError("Unexpected model factory"))
        )
    for name in ("aexecute_simple_task", "aexecute_complex_task"):
        monkeypatch.setattr(
            GameMasterLLM, name, AsyncMock(side_effect=AssertionError("Unexpected model execution"))
        )
    for target in (
        "litellm.acompletion",
        "aiohttp.ClientSession._request",
        "httpx.AsyncHTTPTransport.handle_async_request",
    ):
        monkeypatch.setattr(
            target, AsyncMock(side_effect=AssertionError("Unexpected network request"))
        )


def task_options(workflow, *, kind="npc", provider="comfyui"):
    def preset(name, form, mature):
        return {
            "name": name,
            "generate": deepcopy(workflow),
            "mature_themes": mature,
            "prompt_rules": {
                "format": form,
                "adapt_with_llm": True,
                "prefix": f"{name}_PREFIX",
                "suffix": f"{name}_SUFFIX",
                "instructions": f"Instructions for {name}.",
            },
        }

    return {
        "simple_model_provider": provider,
        "advanced_model_provider": provider,
        "comfyui_presets": {
            "fallback": preset("Fallback", "description", False),
            "task": preset("Task", "tags", True),
            "story": preset("Story", "hybrid", False),
        },
        "comfyui_assignments": {
            "simple": "fallback",
            "advanced": "fallback",
            purpose_for(kind): "task",
        },
    }


def subjects(options, manifest=None):
    user = SimpleNamespace(t2i_settings=options, image_styles_catalog=[], tone_catalog=[])
    adventure = SimpleNamespace(
        selected_tone=None,
        selected_image_styles=[],
        original_manifest=manifest or {},
    )
    return user, adventure


def generation_rules(user, adventure, payload):
    options = story_t2i(user.t2i_settings, adventure)
    profile = (
        "advanced"
        if advanced_for(options, payload.target_type, payload.use_advanced_model)
        else "simple"
    )
    effective = {
        **options,
        "comfyui_profile": profile,
        "image_purpose": purpose_for(payload.target_type),
    }
    return effective, prompt_rules(effective)
