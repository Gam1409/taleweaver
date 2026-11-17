"""Family selection is additive settings data with the existing state/lifecycle fences."""

from copy import deepcopy
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from backend.engine.chpm import control_settings, notebook_store
from backend.engine.chpm.host_state import record
from backend.engine.chpm.notebook import NotebookWorkspace
from backend.engine.chpm.schema import KernelState, Settings
from backend.engine.chpm.state import KEY, load
from backend.engine.turn_replay.snapshot import capture
from backend.models.session_state import SessionState
from backend.models.turn_replay import TurnReplay
from backend.models.user import User
from tests.conftest import TestSessionLocal
from tests.test_chpm_api import PATH, chpm_world, portrait_world, update
from tests.test_chpm_host_state import mind, source
from tests.test_chpm_tool_profiles import PROFILES

__all__ = ["chpm_world", "portrait_world"]


def test_legacy_saved_settings_default_to_auto_without_changing_versions_or_budgets():
    raw = KernelState(settings=Settings(mode="live", actor_ids=["npc"])).model_dump(mode="json")
    del raw["settings"]["tool_profile"]
    before = deepcopy(raw)
    restored = load(SimpleNamespace(entity_states={KEY: raw}))

    assert restored.settings.tool_profile == control_settings.read(raw).tool_profile == "auto"
    assert restored.schema_version == before["schema_version"]
    assert restored.settings.model_dump(exclude={"tool_profile"}) == before["settings"]
    assert raw == before


@pytest.mark.parametrize("profile", PROFILES)
async def test_get_patch_and_disabled_settings_round_trip_each_profile_without_enabling_it(
    auth_client, chpm_world, profile
):
    assert (await auth_client.get(PATH)).json()["settings"]["tool_profile"] == "auto"
    response = await auth_client.patch(PATH, json=update("off", tool_profile=profile))
    assert response.status_code == 200, response.text
    selected = (await auth_client.get(PATH)).json()["settings"]
    assert selected["tool_profile"] == profile and selected["mode"] == "off"
    assert selected["workflow"] == "staged" and selected["agent_steps"] == 0


async def test_unknown_profile_is_rejected_before_settings_or_session_state_change(
    auth_client, chpm_world
):
    before = (await auth_client.get(PATH)).json()
    payload = update("live")
    payload["settings"]["tool_profile"] = "unknown-runtime"
    response = await auth_client.patch(PATH, json=payload)
    assert response.status_code == 422
    assert (await auth_client.get(PATH)).json() == before


async def test_profile_only_patch_preserves_mind_notebook_and_replay_history_with_cas(
    auth_client, chpm_world
):
    response = await auth_client.patch(PATH, json=update("live", tool_profile="anthropic"))
    assert response.status_code == 200, response.text
    selected = response.json()["settings"]
    original = record(
        mind("NPC_NEW", "portrait-session"), source(text="A prior conversation."), minute=1
    )
    async with TestSessionLocal() as db:
        state = await db.scalar(
            select(SessionState).where(SessionState.session_id == "portrait-session")
        )
        current = load(state)
        current.minds["NPC_NEW"] = original
        state.entity_states = {**state.entity_states, KEY: current.model_dump(mode="json")}
        owner = await db.scalar(select(User).where(User.username == "test_user"))
        owner_id = owner.id
        workspace = NotebookWorkspace()
        workspace.write("", '{"private":[null,true,"unchanged"]}', expected_revision=0)
        await notebook_store.persist_workspace(db, original, workspace, owner_id=owner_id)
        saved = await capture(db, "portrait-session")
        db.add(
            TurnReplay(session_id="portrait-session", before=saved, input_text="Hi", status="ready")
        )
        await db.commit()

    changed = {**selected, "tool_profile": "gemma"}
    response = await auth_client.patch(PATH, json={"settings": changed, "expected_revision": 1})
    assert response.status_code == 200, response.text
    assert response.json()["settings"] == changed
    async with TestSessionLocal() as db:
        state = await db.scalar(
            select(SessionState).where(SessionState.session_id == "portrait-session")
        )
        current = load(state)
        assert current.minds["NPC_NEW"] == original and current.usage.calls == 0
        notebook = await notebook_store.load_snapshot(db, original, owner_id)
        assert notebook.payload == workspace.canonical_bytes and notebook.revision == 1
        replay = await db.get(TurnReplay, "portrait-session")
        baseline = replay.before["state"]["entity_states"][KEY]
        assert baseline["settings"] == changed
        assert baseline["minds"]["NPC_NEW"] == original.model_dump(mode="json")
        replay.status = "executing"
        await db.commit()

    assert (
        await auth_client.patch(PATH, json={"settings": selected, "expected_revision": 1})
    ).status_code == 409
    assert (
        await auth_client.patch(PATH, json={"settings": selected, "expected_revision": 2})
    ).status_code == 409
    assert (await auth_client.get(PATH)).json()["settings"] == changed
