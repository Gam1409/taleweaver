"""Real job/cache integration when only the ComfyUI output format or suffix changes."""

from sqlalchemy import select

from backend.core.config import settings
from backend.models.user import User
from tests.conftest import TestSessionLocal
from tests.test_comfyui import workflow
from tests.test_scene_illustrations import finish, illustration_world
from tests.test_visual_plan_pipeline import enable, plan_calls

__all__ = ["workflow", "illustration_world", "plan_calls"]


async def set_format(workflow, format, *, suffix="", instructions="", adapt=True):
    async with TestSessionLocal() as db:
        user = (await db.scalars(select(User))).first()
        user.t2i_settings = {
            **user.t2i_settings,
            "advanced_model_provider": "comfyui",
            "comfyui_presets": {
                "shared": {
                    "name": "Shared",
                    "generate": workflow,
                    "prompt_rules": {
                        "format": format,
                        "adapt_with_llm": adapt,
                        "suffix": suffix,
                        "instructions": instructions,
                    },
                }
            },
            "comfyui_assignments": {"advanced": "shared"},
        }
        await db.commit()


async def test_compatible_formats_reuse_translation_but_audit_each_artifact(
    auth_client,
    illustration_world,
    plan_calls,
    workflow,
    monkeypatch,
):
    monkeypatch.setattr(settings, "ALLOW_PRIVATE_NETWORK_MODELS", True)
    await enable()
    hashes = []
    for format, call_count, plan_hit in [
        ("description", 2, False),
        ("tags", 3, True),
        ("hybrid", 4, True),
        ("description", 4, False),
    ]:
        await set_format(workflow, format)
        result = await finish(auth_client)
        assert result["state"] == "succeeded", result
        plan = result["result"]["generation_details"]["visual_plan"]
        assert plan_calls.await_count == call_count
        assert plan["normalization_cache_hit"] == plan_hit
        assert plan["capabilities"]["format"] == format
        assert plan["provenance"]["facts"]
        hashes.append(plan["plan_hash"])
    assert len(set(hashes)) == 1
    assert result["result"]["generation_details"]["visual_plan"]["cache_hit"]


async def test_suffix_changes_require_audit_not_translation_and_policy_changes_require_both(
    auth_client,
    illustration_world,
    plan_calls,
    workflow,
    monkeypatch,
):
    monkeypatch.setattr(settings, "ALLOW_PRIVATE_NETWORK_MODELS", True)
    await enable()
    await set_format(workflow, "description")
    first = await finish(auth_client)
    assert first["state"] == "succeeded", first
    await set_format(workflow, "description", suffix="pencil sketch")
    second = await finish(auth_client)
    assert second["state"] == "succeeded", second
    assert plan_calls.await_count == 3
    assert plan_calls.call_args.args[4] == "visual_plan_audit"
    assert plan_calls.call_args.args[2]["positive"].endswith("pencil sketch")
    await set_format(workflow, "description", instructions="Use concise vocabulary.")
    third = await finish(auth_client)
    assert third["state"] == "succeeded", third
    assert plan_calls.await_count == 5


async def test_audit_off_format_switch_uses_no_additional_model_calls(
    auth_client,
    illustration_world,
    plan_calls,
    workflow,
    monkeypatch,
):
    monkeypatch.setattr(settings, "ALLOW_PRIVATE_NETWORK_MODELS", True)
    await enable(visual_audit=False)
    await set_format(workflow, "description")
    assert (await finish(auth_client))["state"] == "succeeded"
    await set_format(workflow, "tags")
    result = await finish(auth_client)
    assert result["state"] == "succeeded", result
    assert plan_calls.await_count == 1
    assert result["result"]["generation_details"]["visual_plan"]["semantic_audit"] == "not_run"


async def test_old_legacy_settings_automatically_use_new_pipeline(
    auth_client,
    illustration_world,
    plan_calls,
):
    from copy import deepcopy

    from backend.engine.visual_novel.config import read_settings
    from backend.models.session_state import SessionState

    async with TestSessionLocal() as db:
        state = await db.scalar(select(SessionState).where(SessionState.session_id == "moment"))
        states = deepcopy(state.entity_states)
        states["__manifest_snapshot__"]["original_manifest"]["nsfw_settings"] = {"enabled": False}
        states["__vn_settings__"] = {"visual_preparation": "legacy", "pace": "brisk"}
        state.entity_states = states
        assert read_settings(state).visual_preparation == "plan"
        assert read_settings(state).pace == "brisk"
        await db.commit()
    result = await finish(auth_client)
    assert result["state"] == "succeeded", result
    assert plan_calls.await_count == 2
    response = await auth_client.get(
        "/api/adventures/moment/illustrations", params={"message_id": "moment-reply"}
    )
    assert response.json()["plan_enabled"] is True
    response = await auth_client.patch(
        "/api/adventures/moment/vn-settings", json={"visual_preparation": "legacy"}
    )
    assert response.status_code == 200
    assert response.json()["settings"]["visual_preparation"] == "plan"
    assert response.json()["settings"]["pace"] == "brisk"


async def test_mature_compatibility_is_automatic_and_keeps_existing_prompts(
    auth_client,
    illustration_world,
    plan_calls,
):
    result = await finish(auth_client)
    assert result["state"] == "succeeded", result
    assert plan_calls.await_count == 0
    assert "visual_plan" not in result["result"]["generation_details"]
    assert "Red coat" in illustration_world[0]["prompt"]
    response = await auth_client.get(
        "/api/adventures/moment/illustrations", params={"message_id": "moment-reply"}
    )
    assert response.json()["plan_enabled"] is False


async def test_saved_scenes_prepare_facts_even_when_generic_adaptation_is_disabled(
    auth_client,
    illustration_world,
    plan_calls,
    workflow,
    monkeypatch,
):
    monkeypatch.setattr(settings, "ALLOW_PRIVATE_NETWORK_MODELS", True)
    await enable()
    await set_format(workflow, "tags", adapt=False)
    result = await finish(auth_client)
    assert result["state"] == "succeeded", result
    assert plan_calls.await_count == 2
    assert result["result"]["generation_details"]["visual_plan"]["capabilities"]["format"] == "tags"
