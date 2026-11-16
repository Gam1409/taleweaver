"""Suggest Prompt follows the same effective task policy as the generated image."""

from copy import deepcopy
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy import select

from backend.core import mature_content_prompts
from backend.core.image_purposes import purpose_for
from backend.core.llm_router import GameMasterLLM
from backend.engine import preset_prompt_suggestion as suggestion
from backend.engine.image_prompt_adapter import prepare_prompt
from backend.models import AdventureTemplate, User, WorldEntity
from backend.schemas.adventure_visuals import SuggestPromptRequest
from tests.conftest import TestSessionLocal
from tests.prompt_task_support import (
    generation_rules,
    no_live_prompt_models,
    subjects,
    task_options,
)
from tests.test_comfyui import workflow

__all__ = ["workflow", "no_live_prompt_models"]
pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize("kind", ["npc", "scene", "object", "protagonist", "cover"])
@pytest.mark.parametrize("advanced", [None, False, True])
@pytest.mark.parametrize("provider", ["comfyui", "openai"])
async def test_suggestion_uses_task_rules_and_policy_regardless_of_legacy_quality(
    workflow, monkeypatch, kind, advanced, provider
):
    options = task_options(workflow, kind=kind, provider=provider)
    user, adventure = subjects(options, {"nsfw_settings": {"enabled": True, "level": "soft"}})
    payload = SuggestPromptRequest(
        target_type=kind, target_id="target", use_advanced_model=advanced
    )
    capture = AsyncMock(return_value="A blue coat.")
    monkeypatch.setattr(suggestion, "adapt_body", capture)
    effective, expected = generation_rules(user, adventure, payload)
    original = deepcopy(options)
    assert (
        await suggestion.suggest_preset_prompt(user, adventure, payload, "Keeper", "A blue coat.")
        == "A blue coat."
    )
    assert capture.await_count == 1
    args, kwargs = capture.await_args
    assert args[1] == expected and args[1].format == "tags"
    assert kwargs["mature_themes"] is True and kwargs["nsfw_enabled"] is True
    assert effective["image_purpose"] == purpose_for(kind)
    assert options == original


@pytest.mark.parametrize("source", ["story", "current"])
async def test_story_task_selection_and_current_global_source_remain_authoritative(
    workflow, monkeypatch, source
):
    options = task_options(workflow)
    user, adventure = subjects(
        options,
        {
            "visual_presets": {"npc": "story"},
            "visual_preset_source": source,
        },
    )
    capture = AsyncMock(return_value="A blue coat.")
    monkeypatch.setattr(suggestion, "adapt_body", capture)
    payload = SuggestPromptRequest(target_type="npc", target_id="keeper")
    await suggestion.suggest_preset_prompt(user, adventure, payload, "Keeper", "A blue coat.")
    _, expected = generation_rules(user, adventure, payload)
    assert capture.await_args.args[1] == expected
    assert expected.format == ("tags" if source == "current" else "hybrid")
    assert capture.await_args.kwargs["mature_themes"] is (source == "current")


@pytest.mark.parametrize("enabled", [False, True])
async def test_suggested_manual_body_is_adapted_once_using_task_content_policy(
    workflow, monkeypatch, enabled
):
    options = task_options(workflow)
    user, adventure = subjects(options, {"nsfw_settings": {"enabled": enabled, "level": "soft"}})
    model = AsyncMock(return_value="blue coat")
    llm = type("FakeLLM", (), {"model": "synthetic", "aexecute_simple_task": model})()
    monkeypatch.setattr(GameMasterLLM, "for_role", lambda *_: llm)
    monkeypatch.setattr(mature_content_prompts, "image_prompt_addendum", lambda _: "TASK_POLICY")
    payload = SuggestPromptRequest(target_type="npc", target_id="keeper")
    body = await suggestion.suggest_image_prompt(user, adventure, payload, "Keeper", "A blue coat.")
    system = model.await_args.kwargs["system_prompt"]
    assert '"format": "tags"' in system
    assert ("TASK_POLICY" in system) is enabled
    assert body == "blue coat"
    effective, _ = generation_rules(user, adventure, payload)
    prepared = await prepare_prompt(body, {**effective, "_prompt_prepared": True})
    assert prepared["positive"] == "Task_PREFIX, blue coat, Task_SUFFIX"
    assert model.await_count == 1


async def test_task_without_adaptation_does_not_invoke_a_model(workflow, monkeypatch):
    options = task_options(workflow)
    options["comfyui_presets"]["task"]["prompt_rules"]["adapt_with_llm"] = False
    user, adventure = subjects(options)
    router = Mock(side_effect=AssertionError("Unexpected model call"))
    monkeypatch.setattr(GameMasterLLM, "for_role", router)
    payload = SuggestPromptRequest(target_type="npc", target_id="keeper")
    body = await suggestion.suggest_preset_prompt(
        user, adventure, payload, "Keeper", "A blue coat."
    )
    assert "A blue coat." in body
    router.assert_not_called()


@pytest.mark.parametrize("advanced", [False, True])
async def test_absent_task_uses_existing_legacy_quality_policy(workflow, monkeypatch, advanced):
    options = task_options(workflow)
    del options["comfyui_assignments"]["npc"]
    options["comfyui_assignments"]["advanced"] = "story"
    user, adventure = subjects(options)
    capture = AsyncMock(return_value="A blue coat.")
    monkeypatch.setattr(suggestion, "adapt_body", capture)
    payload = SuggestPromptRequest(
        target_type="npc", target_id="keeper", use_advanced_model=advanced
    )
    await suggestion.suggest_preset_prompt(user, adventure, payload, "Keeper", "A blue coat.")
    assert capture.await_args.args[1].format == ("hybrid" if advanced else "description")


@pytest.mark.parametrize("fallback", ["non_comfyui", "no_rules"])
async def test_generic_suggestion_fallback_remains_available(workflow, monkeypatch, fallback):
    options = task_options(workflow, provider="openai" if fallback == "non_comfyui" else "comfyui")
    options["comfyui_assignments"].pop("npc")
    if fallback == "no_rules":
        options["comfyui_presets"]["fallback"]["prompt_rules"] = None
    user, adventure = subjects(options)
    model = AsyncMock(return_value="generic description")
    llm = type("FakeLLM", (), {"model": "synthetic", "aexecute_simple_task": model})()
    monkeypatch.setattr(GameMasterLLM, "for_role", lambda *_: llm)
    payload = SuggestPromptRequest(target_type="npc", target_id="keeper")
    assert (
        await suggestion.suggest_image_prompt(user, adventure, payload, "Keeper", "A blue coat.")
        == "generic description"
    )
    assert model.await_count == 1
    assert '"format"' not in model.await_args.kwargs["system_prompt"]


@pytest.mark.parametrize("source", ["saved", "current"])
@pytest.mark.parametrize("advanced", [False, True])
async def test_owned_suggest_api_uses_saved_or_current_task_assignment(
    auth_client, workflow, monkeypatch, source, advanced
):
    response = await auth_client.post(
        "/api/adventures/", json={"title": "Archive", "skip_generation": True}
    )
    assert response.status_code == 201
    template_id = response.json()["adventure_id"]
    async with TestSessionLocal() as db:
        user = await db.scalar(select(User).where(User.username == "test_user"))
        user.t2i_settings = task_options(workflow, provider="openai")
        db.add(
            WorldEntity(
                id="KEEPER",
                template_id=template_id,
                entity_type="NPC",
                name="Keeper",
                description="A blue coat.",
                current_scene_id="START",
            )
        )
        await db.commit()
    path = f"/api/adventures/{template_id}/visual-presets"
    chosen = await auth_client.put(path, json={"source": source, "selection": {"npc": "story"}})
    assert chosen.status_code == 200, chosen.text
    assert chosen.json() == {"source": source, "selection": {"npc": "story"}}
    effective = await auth_client.get(
        path, params={"purpose": "npc", "advanced": str(advanced).lower()}
    )
    assert effective.status_code == 200
    assert effective.json()["effective"]["preset_id"] == (
        "task" if source == "current" else "story"
    )
    assert effective.json()["effective"]["profile"] == ("advanced" if advanced else "simple")
    capture = AsyncMock(return_value="blue coat")
    monkeypatch.setattr(suggestion, "adapt_body", capture)
    result = await auth_client.post(
        f"/api/adventures/{template_id}/visuals/suggest-prompt",
        json={"target_type": "npc", "target_id": "KEEPER", "use_advanced_model": advanced},
    )
    assert result.status_code == 200, result.text
    assert result.json() == {"suggested_prompt": "blue coat"}
    assert capture.await_args.args[1].format == ("tags" if source == "current" else "hybrid")
    async with TestSessionLocal() as db:
        template = await db.get(AdventureTemplate, template_id)
        assert template.original_manifest["visual_preset_source"] == source
        assert template.original_manifest["visual_presets"] == {"npc": "story"}
