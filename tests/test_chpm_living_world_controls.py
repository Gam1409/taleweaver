"""Inactive saved controller preferences cannot block existing-session controls."""

from copy import deepcopy
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from backend.engine.chpm.schema import KernelState, Settings
from backend.engine.chpm.state import KEY
from backend.engine.chpm.template_settings import ensure_compatible, ensure_session_compatible
from backend.engine.living_world.schema import Event, Simulation
from backend.engine.living_world.schema import Settings as WorldSettings
from backend.engine.living_world.state import save
from backend.models.session_state import SessionState
from tests.conftest import TestSessionLocal
from tests.test_chpm_api import PATH, chpm_world, update
from tests.test_session_portraits import portrait_world

__all__ = ["chpm_world", "portrait_world"]
WORLD_PATH = "/api/adventures/portrait-session/living-world"


@pytest.mark.parametrize("mode", ["off", "shadow", "live"])
@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.parametrize("decisions", [False, True])
@pytest.mark.parametrize("engine", ["native", "concordia"])
def test_only_two_active_controllers_conflict(mode, enabled, decisions, engine):
    settings = Settings(mode=mode, actor_ids=["NPC_NEW"])
    world = WorldSettings(
        living_world_enabled=enabled, deliberation_enabled=decisions, decision_engine=engine
    ).model_dump()
    if mode == "live" and enabled and decisions:
        with pytest.raises(ValueError, match="private decisions"):
            ensure_compatible(settings, world)
        return
    ensure_compatible(settings, world)
    state = SimpleNamespace(
        entity_states={}, living_world={"settings": world, "events": "unrelated"}
    )
    ensure_session_compatible(state, settings)


async def store_existing_world(*, enabled=False, live_chpm=False):
    async with TestSessionLocal() as db:
        state = await db.scalar(
            select(SessionState).where(SessionState.session_id == "portrait-session")
        )
        simulation = Simulation(
            settings=WorldSettings(living_world_enabled=enabled, deliberation_enabled=True),
            events=[Event(event_id="retained-event", due=10, kind="WAIT")],
        )
        save(state, simulation)
        if live_chpm:
            state.entity_states = {
                **(state.entity_states or {}),
                KEY: KernelState(
                    settings=Settings(mode="live", actor_ids=["NPC_NEW"])
                ).model_dump(),
            }
        await db.commit()
        return deepcopy(state.living_world)


async def test_existing_disabled_world_allows_live_chpm_and_retains_saved_preferences(
    auth_client, chpm_world
):
    original = await store_existing_world()
    response = await auth_client.patch(PATH, json=update("live"))
    assert response.status_code == 200, response.text
    assert response.json()["settings"]["mode"] == "live"
    async with TestSessionLocal() as db:
        state = await db.scalar(
            select(SessionState).where(SessionState.session_id == "portrait-session")
        )
        assert state.living_world == original
        assert state.living_world["settings"]["deliberation_enabled"] is True
        ensure_session_compatible(state)


async def test_existing_active_private_controller_still_blocks_live_chpm(auth_client, chpm_world):
    original = await store_existing_world(enabled=True)
    response = await auth_client.patch(PATH, json=update("live"))
    assert response.status_code == 409
    assert "private decisions" in response.json()["detail"]
    async with TestSessionLocal() as db:
        state = await db.scalar(
            select(SessionState).where(SessionState.session_id == "portrait-session")
        )
        assert state.living_world == original
        assert state.entity_states.get(KEY, {}).get("settings", {}).get("mode", "off") == "off"


async def test_disabled_preferences_can_be_saved_but_reactivation_rechecks_conflict(
    auth_client, chpm_world
):
    original = await store_existing_world(live_chpm=True)
    payload = {"settings": original["settings"], "expected_revision": original["revision"]}
    saved = await auth_client.patch(WORLD_PATH, json=payload)
    assert saved.status_code == 200, saved.text
    retained = saved.json()
    assert retained["settings"]["deliberation_enabled"] is True
    blocked = await auth_client.patch(
        WORLD_PATH,
        json={
            "settings": {**retained["settings"], "living_world_enabled": True},
            "expected_revision": retained["revision"],
        },
    )
    assert blocked.status_code == 409
    allowed = await auth_client.patch(
        WORLD_PATH,
        json={
            "settings": {
                **retained["settings"],
                "living_world_enabled": True,
                "deliberation_enabled": False,
            },
            "expected_revision": retained["revision"],
        },
    )
    assert allowed.status_code == 200, allowed.text
