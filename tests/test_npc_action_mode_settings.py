"""Controller scope comes from the host mode, never a client-selected budget shortcut."""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy import select

from backend.api.routes.adventures.schemas import CreateAdventureTemplatePayload
from backend.engine.chpm.schema import KernelState, Settings
from backend.engine.chpm.state import KEY
from backend.engine.chpm.template_settings import initial_states
from backend.engine.import_build_archive_template import build_archive_template
from backend.engine.import_build_blueprint_template import build_blueprint_template
from backend.engine.import_build_session_template import build_session_template
from backend.engine.turn_replay.snapshot import capture
from backend.engine.visual_novel.config import read_settings
from backend.models.adventure_template import AdventureTemplate
from backend.models.session_state import SessionState
from backend.models.turn_replay import TurnReplay
from tests.conftest import TestSessionLocal
from tests.test_chpm_api import PATH, chpm_world, portrait_world

__all__ = ["chpm_world", "portrait_world"]
TEMPLATE_PATH = "/api/adventures/portrait-template"
PRIVATE_WORLD = {"living_world_enabled": True, "deliberation_enabled": True}


def preferences(**updates):
    return {
        **Settings(
            mode="live",
            actor_ids=["NPC_NEW"],
            workflow="integrated",
            action_tools=True,
            agent_steps=1,
            max_calls_per_turn=7,
        ).model_dump(mode="json"),
        **updates,
    }


async def set_mode(mode):
    async with TestSessionLocal() as db:
        adventure = await db.get(AdventureTemplate, "portrait-template")
        adventure.rule_enforcement_mode = mode
        await db.commit()


@pytest.mark.parametrize("violation", ["budget", "private_controller"])
async def test_vn_template_rechecks_host_policy_for_forged_combat_scope(
    auth_client, chpm_world, violation
):
    settings = preferences(control_scope="combat_actions")
    updates = {"npc_personality_settings": settings}
    if violation == "budget":
        settings["max_calls_per_turn"] = 3
    else:
        updates["living_world_settings"] = PRIVATE_WORLD
    response = await auth_client.patch(TEMPLATE_PATH, json=updates)
    assert response.status_code == 422, response.text
    stored = (await auth_client.get(TEMPLATE_PATH)).json()
    assert stored["npc_personality_settings"] is None
    assert not (stored["living_world_settings"] or {}).get("living_world_enabled", False)


@pytest.mark.parametrize("mode", ["chat", "story"])
async def test_template_rejects_active_controllers_for_unsupported_modes(
    auth_client, chpm_world, mode
):
    response = await auth_client.patch(
        TEMPLATE_PATH,
        json={"rule_enforcement_mode": mode, "npc_personality_settings": preferences()},
    )
    assert response.status_code == 422, response.text
    stored = (await auth_client.get(TEMPLATE_PATH)).json()
    assert stored["rule_enforcement_mode"] == "vn"
    assert stored["npc_personality_settings"] is None


async def test_mode_only_template_change_rebinds_defaults_without_touching_sessions(
    auth_client, chpm_world
):
    assert (
        await auth_client.patch(TEMPLATE_PATH, json={"npc_personality_settings": preferences()})
    ).status_code == 200
    response = await auth_client.patch(TEMPLATE_PATH, json={"rule_enforcement_mode": "rpg"})
    assert response.status_code == 200, response.text
    assert response.json()["npc_personality_settings"]["control_scope"] == "combat_actions"
    assert (await auth_client.get(PATH)).json()["settings"]["mode"] == "off"


async def test_mode_only_template_change_cannot_enable_unsupported_rpg_workflow(
    auth_client, chpm_world
):
    plain = Settings(mode="shadow", actor_ids=["NPC_NEW"]).model_dump()
    assert (
        await auth_client.patch(TEMPLATE_PATH, json={"npc_personality_settings": plain})
    ).status_code == 200
    response = await auth_client.patch(TEMPLATE_PATH, json={"rule_enforcement_mode": "rpg"})
    assert response.status_code == 422, response.text
    assert (await auth_client.get(TEMPLATE_PATH)).json()["rule_enforcement_mode"] == "vn"


@pytest.mark.parametrize("mode, scope", [("vn", "dialogue"), ("rpg", "combat_actions")])
async def test_session_and_replay_enable_pose_tracking_only_for_vn_actions(
    auth_client, chpm_world, mode, scope
):
    await set_mode(mode)
    async with TestSessionLocal() as db:
        saved = await capture(db, "portrait-session")
        db.add(TurnReplay(session_id="portrait-session", before=saved, input_text="Hello"))
        await db.commit()
    response = await auth_client.patch(
        PATH, json={"settings": preferences(), "expected_revision": 0}
    )
    assert response.status_code == 200, response.text
    assert response.json()["settings"]["control_scope"] == scope
    async with TestSessionLocal() as db:
        state = await db.scalar(
            select(SessionState).where(SessionState.session_id == "portrait-session")
        )
        replay = await db.get(TurnReplay, "portrait-session")
        assert read_settings(state).scene_staging is (mode == "vn")
        restored = SimpleNamespace(entity_states=replay.before["state"]["entity_states"])
        assert read_settings(restored).scene_staging is (mode == "vn")


async def test_scope_change_clears_obsolete_control_and_replay_actors(auth_client, chpm_world):
    from tests.test_chpm_kernel import decision
    from tests.test_chpm_memory import entry

    assert (
        await auth_client.patch(PATH, json={"settings": preferences(), "expected_revision": 0})
    ).status_code == 200
    async with TestSessionLocal() as db:
        state = await db.scalar(
            select(SessionState).where(SessionState.session_id == "portrait-session")
        )
        value = deepcopy(state.entity_states)
        value[KEY]["actors"] = {"NPC_NEW": decision().model_dump()}
        value[KEY]["memories"] = {"NPC_NEW": [entry(observer="NPC_NEW").model_dump()]}
        value[KEY]["usage"]["calls"] = 4
        state.entity_states = value
        await db.flush()
        saved = await capture(db, "portrait-session")
        db.add(TurnReplay(session_id="portrait-session", before=saved, input_text="Hello"))
        await db.commit()
    await set_mode("rpg")
    response = await auth_client.patch(
        PATH, json={"settings": preferences(), "expected_revision": 1}
    )
    assert response.status_code == 200, response.text
    assert response.json()["trace"] == []
    assert response.json()["memory"] == {}
    assert response.json()["usage"]["calls"] == 0
    async with TestSessionLocal() as db:
        replay = await db.get(TurnReplay, "portrait-session")
        restored = replay.before["state"]["entity_states"][KEY]
        assert restored["actors"] == restored["memories"] == {}


@pytest.mark.parametrize("mode, shadow", [("chat", False), ("unknown", False), ("rpg", True)])
async def test_unsupported_session_mode_is_rejected_without_writes(
    auth_client, chpm_world, mode, shadow
):
    await set_mode(mode)
    before = (await auth_client.get(PATH)).json()
    response = await auth_client.patch(
        PATH,
        json={
            "settings": preferences(mode="shadow" if shadow else "live"),
            "expected_revision": 0,
        },
    )
    assert response.status_code in {409, 422}, response.text
    after = (await auth_client.get(PATH)).json()
    assert after["settings"] == before["settings"]
    assert after["revision"] == before["revision"]


@pytest.mark.parametrize("violation", ["budget", "private_controller"])
def test_creation_cannot_trust_client_scope_to_bypass_vn_checks(violation):
    raw = {
        "title": "Mode policy",
        "rule_enforcement_mode": "vn",
        "npc_personality_settings": preferences(control_scope="combat_actions"),
    }
    if violation == "budget":
        raw["npc_personality_settings"]["max_calls_per_turn"] = 3
    else:
        raw["living_world_settings"] = PRIVATE_WORLD
    with pytest.raises(ValueError):
        CreateAdventureTemplatePayload.model_validate(raw)


@pytest.mark.parametrize("builder", ["blueprint", "archive", "session"])
@pytest.mark.parametrize("mode", ["vn", "rpg"])
def test_imports_rebind_scope_from_host_mode_before_validating_budget(builder, mode):
    raw = {
        "title": "Mode policy",
        "rule_enforcement_mode": mode,
        "npc_personality_settings": preferences(
            control_scope="combat_actions", max_calls_per_turn=3
        ),
    }

    def build():
        if builder == "blueprint":
            return build_blueprint_template({}, raw, raw, "owner", None, mode, False)
        if builder == "archive":
            return build_archive_template("copy", "owner", raw, raw, None, mode, False, None, None)
        return build_session_template({"adventure": raw}, SimpleNamespace(id="owner"), None)

    if mode == "vn":
        with pytest.raises(ValueError):
            build()
        return
    template = build()
    assert template.npc_personality_settings["control_scope"] == "combat_actions"
    states = initial_states(template, {})
    assert states[KEY]["settings"]["control_scope"] == "combat_actions"
    assert read_settings(SimpleNamespace(entity_states=states)).scene_staging is False


@pytest.mark.parametrize("builder", ["blueprint", "archive", "session"])
def test_imported_defaults_cannot_bypass_private_controller_conflict(builder):
    raw = {
        "title": "Mode policy",
        "rule_enforcement_mode": "vn",
        "npc_personality_settings": preferences(control_scope="combat_actions"),
        "living_world_settings": PRIVATE_WORLD,
    }
    with pytest.raises(ValueError, match="private decisions"):
        if builder == "blueprint":
            build_blueprint_template({}, raw, raw, "owner", None, "vn", False)
        elif builder == "archive":
            build_archive_template("copy", "owner", raw, raw, None, "vn", False, None, None)
        else:
            build_session_template({"adventure": raw}, SimpleNamespace(id="owner"), None)


@pytest.mark.parametrize("mode, scope", [("vn", "combat_actions"), ("rpg", "dialogue")])
async def test_mismatched_saved_controller_remains_inactive_until_owner_settings_saved(
    monkeypatch, mode, scope
):
    """An imported scope mismatch cannot run either controller or rewrite saved history."""
    from backend.engine.chpm import inference, runtime
    from backend.engine.npc_actions import combat_binding
    from tests.test_chpm_runtime import manager

    host, actor = manager()
    host.adventure.rule_enforcement_mode = mode
    settings = Settings.model_validate(preferences(control_scope=scope, actor_ids=[actor.id]))
    host.state.entity_states[KEY] = KernelState(settings=settings).model_dump(mode="json")
    original = deepcopy(host.state.entity_states)
    model = AsyncMock(side_effect=AssertionError("A mismatched controller cannot infer."))
    selector = Mock(side_effect=AssertionError("A mismatched controller cannot bind combat."))
    monkeypatch.setattr(inference, "request", model)
    monkeypatch.setattr(combat_binding, "make_selector", selector)
    combat_binding.bind(host, "/wait")
    assert host.npc_ability_selector is None
    assert await runtime.prepare(host, "Hello", [actor]) == ""
    assert host.state.entity_states == original
    model.assert_not_called()
    selector.assert_not_called()
