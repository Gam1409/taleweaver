"""Transport validation follows the actual host before deriving controller authority."""

from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy import select

from backend.engine.chpm.schema import KernelState, Settings
from backend.engine.chpm.state import KEY
from backend.models.session_state import SessionState
from tests.conftest import TestSessionLocal
from tests.test_chpm_api import PATH, chpm_world, portrait_world
from tests.test_npc_action_mode_settings import TEMPLATE_PATH, set_mode

__all__ = ["chpm_world", "portrait_world"]


def editor_settings(**changes):
    return {
        "mode": "live",
        "actor_ids": ["NPC_NEW"],
        "workflow": "integrated",
        "agent_steps": 1,
        "action_tools": True,
        "max_input_chars": 48000,
        "max_calls_per_turn": 3,
        **changes,
    }


async def test_rpg_editor_defaults_use_combat_budget_before_dialogue_reserve(
    auth_client, chpm_world
):
    await set_mode("rpg")
    response = await auth_client.patch(
        TEMPLATE_PATH, json={"npc_personality_settings": editor_settings()}
    )
    assert response.status_code == 200, response.text
    settings = response.json()["npc_personality_settings"]
    assert settings["control_scope"] == "combat_actions"
    assert settings["max_calls_per_turn"] == 3


async def test_new_rpg_session_can_save_the_host_budget_with_legacy_dialogue_scope(
    auth_client, chpm_world
):
    await set_mode("rpg")
    status = (await auth_client.get(PATH)).json()
    assert status["settings"]["control_scope"] == "dialogue"
    response = await auth_client.patch(
        PATH,
        json={
            "settings": {**status["settings"], **editor_settings()},
            "expected_revision": status["revision"],
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["settings"]["control_scope"] == "combat_actions"
    assert response.json()["settings"]["max_calls_per_turn"] == 3


async def test_previous_combat_budget_stays_readable_until_owner_explicitly_repairs_it(
    auth_client, chpm_world
):
    await set_mode("rpg")
    value = KernelState(
        settings=Settings.model_validate(
            editor_settings(control_scope="combat_actions", agent_steps=3, max_calls_per_turn=9)
        )
    ).model_dump()
    # This was a valid saved controller before the initiative reserve was corrected.
    value["settings"]["max_calls_per_turn"] = 8
    async with TestSessionLocal() as db:
        state = await db.scalar(
            select(SessionState).where(SessionState.session_id == "portrait-session")
        )
        state.entity_states = {**state.entity_states, KEY: value}
        await db.commit()
    response = await auth_client.get(PATH)
    assert response.status_code == 200, response.text
    status = response.json()
    assert status["settings"]["max_calls_per_turn"] == 8
    assert status["required_call_budget"] == 9
    response = await auth_client.patch(
        PATH, json={"settings": status["settings"], "expected_revision": status["revision"]}
    )
    assert response.status_code == 422, response.text
    response = await auth_client.patch(
        PATH,
        json={
            "settings": {**status["settings"], "max_output_tokens": 1400},
            "expected_revision": status["revision"],
        },
    )
    assert response.status_code == 422, response.text
    assert (await auth_client.get(PATH)).json()["settings"] == status["settings"]
    response = await auth_client.patch(
        PATH,
        json={
            "settings": {**status["settings"], "max_calls_per_turn": 9},
            "expected_revision": status["revision"],
        },
    )
    assert response.status_code == 200, response.text
    repaired = response.json()
    assert repaired["settings"]["max_calls_per_turn"] == 9
    response = await auth_client.patch(
        PATH, json={"settings": repaired["settings"], "expected_revision": repaired["revision"]}
    )
    assert response.status_code == 200, response.text
    assert response.json()["revision"] == repaired["revision"]


async def test_returned_vn_session_can_select_observe_with_saved_combat_scope(
    auth_client, chpm_world
):
    await set_mode("rpg")
    response = await auth_client.patch(
        PATH,
        json={"settings": editor_settings(control_scope="combat_actions"), "expected_revision": 0},
    )
    assert response.status_code == 200, response.text
    await set_mode("vn")
    status = (await auth_client.get(PATH)).json()
    assert status["host_mode"] == "vn"
    response = await auth_client.patch(
        PATH,
        json={
            "settings": {**status["settings"], "mode": "shadow"},
            "expected_revision": status["revision"],
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["settings"]["control_scope"] == "dialogue"
    assert response.json()["settings"]["mode"] == "shadow"


@pytest.mark.parametrize("path", [PATH, TEMPLATE_PATH])
@pytest.mark.parametrize(
    "changes",
    [
        {"unknown_setting": True},
        {"max_calls_per_turn": True},
        {"max_calls_per_turn": "3"},
        {"agent_steps": "1"},
        {"action_tools": "true"},
        {"control_scope": "invented"},
        {"actor_ids": [7]},
    ],
)
async def test_host_neutral_transport_keeps_closed_strict_scalar_contract(
    auth_client, chpm_world, path, changes
):
    await set_mode("rpg")
    before = (await auth_client.get(path)).json()
    settings = editor_settings(**changes)
    payload = (
        {"settings": settings, "expected_revision": before["revision"]}
        if path == PATH
        else {"npc_personality_settings": settings}
    )
    response = await auth_client.patch(path, json=payload)
    assert response.status_code == 422, response.text
    after = (await auth_client.get(path)).json()
    key = "settings" if path == PATH else "npc_personality_settings"
    assert after[key] == before[key]


@pytest.mark.parametrize("path", [PATH, TEMPLATE_PATH])
@pytest.mark.parametrize(
    "changes",
    [
        {"actor_ids": ["NPC_NEW", "NPC_NEW"]},
        {"actor_ids": []},
        {"workflow": "staged"},
        {"agent_steps": 0},
    ],
)
async def test_host_normalization_still_validates_complete_controller_before_writes(
    auth_client, chpm_world, path, changes
):
    await set_mode("rpg")
    before = (await auth_client.get(path)).json()
    settings = editor_settings(**changes)
    payload = (
        {"settings": settings, "expected_revision": before["revision"]}
        if path == PATH
        else {"npc_personality_settings": settings}
    )
    response = await auth_client.patch(path, json=payload)
    assert response.status_code == 422, response.text
    after = (await auth_client.get(path)).json()
    key = "settings" if path == PATH else "npc_personality_settings"
    assert after[key] == before[key]


async def test_saved_semantic_preference_does_not_warm_combat_control(
    auth_client, chpm_world, monkeypatch
):
    from backend.engine.memory_rag import worker

    mark, schedule = AsyncMock(), Mock()
    monkeypatch.setattr(worker, "mark_dirty", mark)
    monkeypatch.setattr(worker, "schedule", schedule)
    settings = Settings(
        mode="live",
        actor_ids=["NPC_NEW"],
        action_tools=True,
        workflow="integrated",
        agent_steps=1,
        max_input_chars=48000,
        semantic_memory=True,
        notebook_enabled=True,
    ).model_dump()
    response = await auth_client.patch(PATH, json={"settings": settings, "expected_revision": 0})
    assert response.status_code == 200, response.text
    mark.reset_mock()
    schedule.reset_mock()
    await set_mode("rpg")
    response = await auth_client.patch(
        PATH, json={"settings": response.json()["settings"], "expected_revision": 1}
    )
    assert response.status_code == 200, response.text
    assert response.json()["settings"]["semantic_memory"] is True
    assert response.json()["settings"]["notebook_enabled"] is True
    mark.assert_not_awaited()
    schedule.assert_not_called()
    await set_mode("vn")
    response = await auth_client.patch(
        PATH, json={"settings": response.json()["settings"], "expected_revision": 2}
    )
    assert response.status_code == 200, response.text
    assert response.json()["settings"]["semantic_memory"] is True
    assert response.json()["settings"]["notebook_enabled"] is True
    assert mark.await_count == schedule.call_count == 1
