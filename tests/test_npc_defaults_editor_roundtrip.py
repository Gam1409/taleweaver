"""Editor round trips preserve dormant preferences without granting new authority."""

from copy import deepcopy

import pytest
from sqlalchemy import select

from backend.core.llm_router import GameMasterLLM
from backend.engine.chpm.schema import Settings
from backend.engine.chpm.state import load
from backend.engine.visual_novel.config import read_settings
from backend.models.adventure_template import AdventureTemplate
from backend.models.session_state import SessionState
from tests.conftest import TestSessionLocal
from tests.test_chpm_api import chpm_world, portrait_world

__all__ = ["chpm_world", "portrait_world"]
PATH = "/api/adventures/portrait-template"


@pytest.fixture(autouse=True)
def forbid_inference(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("Saving inactive defaults must not request model inference.")

    for method in (
        "aexecute_simple_task",
        "aexecute_complex_task",
        "aexecute_tool_turn",
        "execute_simple_task",
        "execute_complex_task",
        "stream_simple_task",
    ):
        monkeypatch.setattr(GameMasterLLM, method, forbidden)


def legacy_preferences(mode):
    values = Settings(
        mode=mode,
        actor_ids=["NPC_NEW"],
        workflow="integrated",
        agent_steps=2,
        notebook_enabled=True,
        semantic_memory=True,
        tool_protocol="json",
        memory_limit=17,
        max_calls_per_turn=12,
    ).model_dump(mode="json")
    for key in ("control_scope", "action_tools", "tool_profile"):
        values.pop(key)
    return values


async def save_existing(host, preferences):
    async with TestSessionLocal() as db:
        adventure = await db.get(AdventureTemplate, "portrait-template")
        adventure.rule_enforcement_mode = host
        adventure.npc_personality_settings = deepcopy(preferences)
        state = await db.scalar(
            select(SessionState).where(SessionState.session_id == "portrait-session")
        )
        before = deepcopy(state.entity_states)
        await db.commit()
    return before


@pytest.mark.parametrize("host", ["rpg", "story", "chat"])
@pytest.mark.parametrize("mode", ["live", "shadow"])
async def test_full_editor_save_preserves_unchanged_legacy_dormant_preferences(
    auth_client, chpm_world, host, mode
):
    before = await save_existing(host, legacy_preferences(mode))
    loaded = await auth_client.get(PATH)
    assert loaded.status_code == 200, loaded.text
    defaults = loaded.json()["npc_personality_settings"]
    response = await auth_client.patch(
        PATH,
        json={
            "title": "An unrelated editor change",
            "rule_enforcement_mode": host,
            "npc_personality_settings": defaults,
        },
    )
    assert response.status_code == 200, response.text
    saved = response.json()
    assert saved["title"] == "An unrelated editor change"
    assert saved["npc_personality_settings"] == defaults
    assert saved["npc_personality_settings"]["control_scope"] == "dialogue"
    assert saved["npc_personality_settings"]["action_tools"] is False
    async with TestSessionLocal() as db:
        state = await db.scalar(
            select(SessionState).where(SessionState.session_id == "portrait-session")
        )
        assert state.entity_states == before


@pytest.mark.parametrize("host", ["rpg", "story", "chat"])
@pytest.mark.parametrize("field,value", [("tool_profile", "qwen"), ("max_output_tokens", 1400)])
async def test_actual_default_changes_still_require_valid_current_host_authority(
    auth_client, chpm_world, host, field, value
):
    await save_existing(host, legacy_preferences("live"))
    original = (await auth_client.get(PATH)).json()
    changed = {**original["npc_personality_settings"], field: value}
    response = await auth_client.patch(
        PATH,
        json={
            "title": "A rejected defaults change",
            "rule_enforcement_mode": host,
            "npc_personality_settings": changed,
        },
    )
    assert response.status_code == 422, response.text
    saved = (await auth_client.get(PATH)).json()
    assert saved["npc_personality_settings"] == original["npc_personality_settings"]
    assert saved["title"] == original["title"]


async def test_unchanged_vn_defaults_still_reject_a_new_private_controller_conflict(
    auth_client, chpm_world
):
    saved = await auth_client.patch(
        PATH, json={"npc_personality_settings": legacy_preferences("live")}
    )
    assert saved.status_code == 200, saved.text
    original = saved.json()
    response = await auth_client.patch(
        PATH,
        json={
            "rule_enforcement_mode": "vn",
            "npc_personality_settings": original["npc_personality_settings"],
            "living_world_settings": {
                "living_world_enabled": True,
                "deliberation_enabled": True,
            },
        },
    )
    assert response.status_code == 422, response.text
    current = (await auth_client.get(PATH)).json()
    assert current["npc_personality_settings"] == original["npc_personality_settings"]
    assert current["living_world_settings"] == original["living_world_settings"]


@pytest.mark.parametrize("host", ["vn", "rpg"])
@pytest.mark.parametrize("field,value", [("actor_ids", []), ("tool_profile", "retired-profile")])
async def test_valid_defaults_can_replace_invalid_legacy_preferences(
    auth_client, chpm_world, host, field, value
):
    invalid = {**legacy_preferences("live"), field: value}
    await save_existing(host, invalid)
    replacement = Settings(
        mode="off", actor_ids=["NPC_NEW"], tool_profile="qwen", model_role="small"
    ).model_dump(mode="json")
    response = await auth_client.patch(PATH, json={"npc_personality_settings": replacement})
    assert response.status_code == 200, response.text
    saved = (await auth_client.get(PATH)).json()["npc_personality_settings"]
    assert saved["mode"] == "off"
    assert saved["tool_profile"] == "qwen" and saved["actor_ids"] == ["NPC_NEW"]
    assert saved["control_scope"] == ("combat_actions" if host == "rpg" else "dialogue")


@pytest.mark.parametrize("host", ["vn", "rpg"])
@pytest.mark.parametrize("field,value", [("actor_ids", []), ("tool_profile", "retired-profile")])
async def test_invalid_legacy_preferences_are_not_preserved_by_an_unchanged_invalid_payload(
    auth_client, chpm_world, host, field, value
):
    invalid = {**legacy_preferences("live"), field: value}
    before = await save_existing(host, invalid)
    response = await auth_client.patch(
        PATH,
        json={
            "title": "A rejected invalid round trip",
            "rule_enforcement_mode": host,
            "npc_personality_settings": invalid,
        },
    )
    assert response.status_code == 422, response.text
    async with TestSessionLocal() as db:
        adventure = await db.get(AdventureTemplate, "portrait-template")
        assert adventure.npc_personality_settings == invalid
        assert adventure.title != "A rejected invalid round trip"
        state = await db.scalar(
            select(SessionState).where(SessionState.session_id == "portrait-session")
        )
        assert state.entity_states == before


@pytest.mark.parametrize("mode", ["live", "shadow"])
async def test_existing_defaults_still_derive_authority_before_validating_client_scope(
    auth_client, chpm_world, mode
):
    saved = await auth_client.patch(
        PATH, json={"npc_personality_settings": legacy_preferences("live")}
    )
    assert saved.status_code == 200, saved.text
    proposed = {
        **saved.json()["npc_personality_settings"],
        "mode": mode,
        "control_scope": "combat_actions",
    }
    response = await auth_client.patch(PATH, json={"npc_personality_settings": proposed})
    assert response.status_code == 200, response.text
    assert response.json()["npc_personality_settings"]["control_scope"] == "dialogue"
    assert response.json()["npc_personality_settings"]["mode"] == mode


@pytest.mark.parametrize("host", ["vn", "rpg"])
@pytest.mark.parametrize("actions", [False, True])
async def test_new_standard_sessions_keep_normalized_host_preferences_without_activating(
    auth_client, chpm_world, host, actions
):
    await save_existing(host, None)
    defaults = Settings(
        mode="off",
        actor_ids=["NPC_NEW"],
        workflow="integrated",
        agent_steps=2,
        action_tools=actions,
        tool_profile="qwen",
        tool_protocol="json",
        model_role="small",
        max_input_chars=64000,
        max_calls_per_turn=12,
        notebook_enabled=True,
        semantic_memory=True,
        memory_limit=17,
        failure_policy="strict",
    ).model_dump(mode="json")
    saved = await auth_client.patch(PATH, json={"npc_personality_settings": defaults})
    assert saved.status_code == 200, saved.text
    expected = saved.json()["npc_personality_settings"]
    assert expected["control_scope"] == ("combat_actions" if host == "rpg" else "dialogue")
    started = await auth_client.post(PATH + "/sessions/start")
    assert started.status_code == 201, started.text
    identifier = started.json()["game_id"]
    response = await auth_client.get(f"/api/adventures/{identifier}/chpm")
    assert response.status_code == 200, response.text
    assert response.json()["settings"] == expected
    assert response.json()["usage"]["calls"] == 0
    assert response.json()["required_call_budget"] == 0
    async with TestSessionLocal() as db:
        state = await db.scalar(select(SessionState).where(SessionState.session_id == identifier))
        kernel = load(state)
        assert kernel.settings.mode == "off"
        assert kernel.minds == kernel.actors == {}
        assert read_settings(state).scene_staging is False
