"""Owner isolation, duplicate commands, foreground exclusion and independent presence."""

import asyncio

import pytest
import pytest_asyncio
from sqlalchemy import select

from backend.engine.living_world import rules
from backend.engine.living_world.foreground import check
from backend.engine.living_world.schema import Event
from backend.engine.living_world.state import load, save
from backend.engine.visual_novel.concurrency import SessionBusyError, session_write_lease
from backend.models.game_session import GameSession
from backend.models.session_state import SessionState
from backend.models.user import User
from tests.conftest import TestSessionLocal
from tests.test_living_world import seed

BASE = "/api/adventures/session-1/living-world"


@pytest_asyncio.fixture
async def world(auth_client):
    async with TestSessionLocal() as db:
        _, state = await seed(db)
        owner = await db.scalar(select(User).where(User.username == "test_user"))
        game = await db.get(GameSession, "session-1")
        game.user_id = state.user_id = owner.id
        await db.commit()
    return auth_client


async def configure(world, **kwargs):
    current = (await world.get(BASE)).json()
    response = await world.patch(
        BASE,
        json={
            "expected_revision": current["revision"],
            "settings": {**current["settings"], "living_world_enabled": True, **kwargs},
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


async def test_feature_is_disabled_and_presence_does_not_write_old_sessions(world):
    response = await world.get(BASE)
    assert not response.json()["settings"]["living_world_enabled"]
    assert (
        await world.post(BASE + "/presence", json={"client_id": "tab", "active": True})
    ).status_code == 200
    async with TestSessionLocal() as db:
        state = await db.scalar(select(SessionState).where(SessionState.session_id == "session-1"))
        game = await db.get(GameSession, "session-1")
        assert state.living_world is None and game.living_world_presence is None


async def test_settings_are_versioned_and_busy_foreground_does_not_block_heartbeats(world):
    result = await configure(world)
    with session_write_lease("session-1"):
        changed = await world.patch(
            BASE, json={"settings": result["settings"], "expected_revision": result["revision"]}
        )
        assert changed.status_code == 409
        heartbeat = await world.post(BASE + "/presence", json={"client_id": "tab", "active": True})
        assert heartbeat.status_code == 200, heartbeat.text
    repeated = await world.patch(
        BASE, json={"settings": result["settings"], "expected_revision": 0}
    )
    assert repeated.status_code == 409


async def test_private_journal_is_admin_only_and_wrong_owner_gets_no_state(world):
    await configure(world)
    event = {"event_id": "secret-plan", "due": 10, "kind": "DECISION", "actor": "MIRINDA"}
    assert (await world.post(BASE + "/events", json=event)).status_code == 200
    assert (await world.post(BASE + "/events", json=event)).status_code == 409
    assert "secret-plan" not in (await world.get(BASE)).text
    async with TestSessionLocal() as db:
        owner = await db.scalar(select(User).where(User.username == "test_user"))
        owner.role = "user"
        await db.commit()
    assert (await world.get(BASE + "/events")).status_code == 403
    assert (await world.get("/api/adventures/not-owned/living-world")).status_code == 404


async def test_pending_catchup_blocks_player_turn_without_invoking_a_model(world):
    await configure(world, mode="CATCH_UP")
    async with TestSessionLocal() as db:
        state = await db.scalar(select(SessionState).where(SessionState.session_id == "session-1"))
        game = await db.get(GameSession, "session-1")
        game.living_world_presence = {"offline_total": 7200}
        await db.commit()
        with pytest.raises(SessionBusyError, match="catch-up"):
            await check(db, "session-1", game.user_id)
        assert load(state).target == 120
    current = (await world.get(BASE)).json()
    done = await world.post(BASE + "/resume", json={"expected_revision": current["revision"]})
    assert done.status_code == 200, done.text
    assert done.json()["cursor"] == 120
    repeated = await world.post(BASE + "/resume", json={"expected_revision": current["revision"]})
    assert repeated.status_code == 409


async def test_two_clients_cannot_run_twice_and_stop_occurs_at_event_boundary(world, monkeypatch):
    await configure(world, mode="CATCH_UP")
    async with TestSessionLocal() as db:
        state = await db.scalar(select(SessionState).where(SessionState.session_id == "session-1"))
        sim = load(state)
        sim.target = 100
        sim.events = [
            Event(event_id="one", due=10, kind="WAIT"),
            Event(event_id="two", due=20, kind="WAIT"),
        ]
        save(state, sim)
        await db.commit()
    reached, release = asyncio.Event(), asyncio.Event()
    original = rules.apply

    async def paused(db, state, event):
        reached.set()
        await release.wait()
        await original(db, state, event)

    monkeypatch.setattr(rules, "apply", paused)
    revision = (await world.get(BASE)).json()["revision"]
    task = asyncio.create_task(world.post(BASE + "/resume", json={"expected_revision": revision}))
    try:
        await asyncio.wait_for(reached.wait(), timeout=5)
        duplicate = await world.post(BASE + "/resume", json={"expected_revision": revision})
        assert duplicate.status_code == 409
        assert (await world.post(BASE + "/stop")).json()["stop_requested"]
    finally:
        release.set()
    response = await task
    assert response.status_code == 200, response.text
    assert response.json()["cursor"] == 10
    assert response.json()["pending_events"] == 1


async def test_budget_can_be_increased_and_feature_disabled_without_losing_pending_target(world):
    await configure(world, mode="CATCH_UP", max_events=0)
    async with TestSessionLocal() as db:
        state = await db.scalar(select(SessionState).where(SessionState.session_id == "session-1"))
        sim = load(state)
        sim.target = 100
        save(state, sim)
        await db.commit()
    current = (await world.get(BASE)).json()
    settings = {**current["settings"], "max_events": 20, "living_world_enabled": False}
    response = await world.patch(
        BASE, json={"expected_revision": current["revision"], "settings": settings}
    )
    assert response.status_code == 200, response.text
    assert response.json()["target"] == 100
    async with TestSessionLocal() as db:
        game = await db.get(GameSession, "session-1")
        await check(db, "session-1", game.user_id)
