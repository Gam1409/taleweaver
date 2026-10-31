"""Real SQL, controlled inference: private facts, stale replies, budgets and lifecycle."""

import asyncio
import json

import pytest
import pytest_asyncio
from sqlalchemy import select

from backend.core.config import settings
from backend.core.llm_router import GameMasterLLM
from backend.engine.living_world import concordia_adapter, deliberation
from backend.engine.living_world.decisions import Decision, PrivateNotes
from backend.engine.living_world.narration import private_context
from backend.engine.living_world.schema import Event
from backend.engine.living_world.state import fork, load, save
from backend.engine.memory_rag.scheduling import scheduler
from backend.engine.visual_novel.concurrency import session_write_lease
from backend.models.session_state import SessionState
from backend.models.user import User
from tests import test_living_world_api as api
from tests.conftest import TestSessionLocal

BASE, configure, world = api.BASE, api.configure, api.world


@pytest_asyncio.fixture
async def ready(world, monkeypatch):
    monkeypatch.setattr(settings, "INFERENCE_SERIALIZATION_ENABLED", True)
    monkeypatch.setattr(scheduler, "grace_seconds", 0)
    async with TestSessionLocal() as db:
        user = await db.scalar(select(User).where(User.username == "test_user"))
        user.llm_settings = {"small_model_provider": "ollama", "small_model": "test"}
        await db.commit()
    await configure(world, deliberation_enabled=True, mode="CATCH_UP")
    async with TestSessionLocal() as db:
        state = await db.scalar(select(SessionState).where(SessionState.session_id == "session-1"))
        sim = load(state)
        sim.target = 60
        sim.events = [Event(event_id="choice", due=10, kind="DECISION", actor="LILI")]
        save(state, sim)
        await db.commit()
    return world


async def post(client, suffix="/deliberate"):
    revision = (await client.get(BASE)).json()["revision"]
    return await client.post(BASE + suffix, json={"expected_revision": revision})


def fake(monkeypatch, **changes):
    captured = []

    async def generate(self, system, user, model, **kwargs):
        captured.append(json.loads(user))
        return (
            Decision(action="WAIT", goal="Find a quiet place.", belief="The hall might be busy.")
            .model_copy(update=changes)
            .model_dump_json()
        )

    monkeypatch.setattr(GameMasterLLM, "aexecute_simple_task", generate)
    return captured


async def test_valid_move_commits_only_action_and_private_notes(ready, monkeypatch):
    captured = fake(monkeypatch, action="MOVE", destination="ROOM")
    response = await post(ready)
    assert response.status_code == 200, response.text
    assert response.json()["llm_calls"] == 1
    assert "quiet" not in response.text and "belief" not in response.text
    async with TestSessionLocal() as db:
        state = await db.scalar(select(SessionState).where(SessionState.session_id == "session-1"))
        sim = load(state)
        assert state.entity_states["LILI"]["current_scene_id"] == "ROOM"
        assert sim.events[0].kind == "MOVE" and sim.events[0].status == "COMMITTED"
        assert sim.private_notes["LILI"].goal == "Find a quiet place."
        assert "MIRINDA" not in sim.private_notes
    assert "plot" not in captured[0] and "ROOM" in captured[0]["destinations"]


@pytest.mark.parametrize("action", ["disable", "rewind", "world"])
async def test_late_answer_is_discarded_and_sql_is_not_locked(ready, monkeypatch, action):
    entered, release = asyncio.Event(), asyncio.Event()

    async def generate(*args, **kwargs):
        entered.set()
        await release.wait()
        return Decision(
            action="MOVE", destination="ROOM", goal="Secret.", belief="Maybe."
        ).model_dump_json()

    monkeypatch.setattr(GameMasterLLM, "aexecute_simple_task", generate)
    task = asyncio.create_task(post(ready))
    await asyncio.wait_for(entered.wait(), 5)
    try:
        # A separate writer obtains the lease and commits while inference is waiting.
        with session_write_lease("session-1"):
            async with TestSessionLocal() as db:
                state = await db.scalar(
                    select(SessionState).where(SessionState.session_id == "session-1")
                )
                if action == "rewind":
                    state.living_world = fork(state.living_world)
                elif action == "world":
                    state.entity_states = {"LILI": {"current_scene_id": "START", "mood": "busy"}}
                else:
                    sim = load(state)
                    sim.settings.living_world_enabled = False
                    save(state, sim)
                await db.commit()
    finally:
        release.set()
    response = await task
    assert response.status_code == 409, response.text
    async with TestSessionLocal() as db:
        state = await db.scalar(select(SessionState).where(SessionState.session_id == "session-1"))
        assert not load(state).private_notes
        assert (state.entity_states or {}).get("LILI", {}).get(
            "current_scene_id", "START"
        ) == "START"


async def test_duplicate_and_stop_do_not_apply_results(ready, monkeypatch):
    entered = asyncio.Event()

    async def generate(*args, **kwargs):
        entered.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(GameMasterLLM, "aexecute_simple_task", generate)
    task = asyncio.create_task(post(ready))
    await asyncio.wait_for(entered.wait(), 5)
    assert (await post(ready)).status_code == 409
    assert (await ready.post(BASE + "/stop")).json()["stop_requested"]
    response = await asyncio.wait_for(task, 5)
    assert response.status_code == 409
    assert "session-1" not in deliberation.pending
    journal = (await ready.get(BASE + "/events")).json()
    assert journal["private_notes"] == {} and journal["events"][0]["attempts"] == 1


async def test_invalid_output_has_no_world_effect_and_attempt_limit(ready, monkeypatch):
    async def generate(*args, **kwargs):
        return '{"action": "teleport"}'

    monkeypatch.setattr(GameMasterLLM, "aexecute_simple_task", generate)
    assert (await post(ready)).status_code == 502
    assert (await post(ready)).status_code == 502
    assert (await post(ready)).status_code == 409
    journal = (await ready.get(BASE + "/events")).json()
    assert journal["private_notes"] == {} and journal["events"][0]["status"] == "WAITING_FOR_LLM"


async def test_disabled_admission_and_budget_do_not_call_model(ready, monkeypatch):
    captured = fake(monkeypatch)
    monkeypatch.setattr(settings, "INFERENCE_SERIALIZATION_ENABLED", False)
    assert (await post(ready)).status_code == 409
    monkeypatch.setattr(settings, "INFERENCE_SERIALIZATION_ENABLED", True)
    await configure(ready, deliberation_enabled=True, mode="CATCH_UP", max_deliberations=0)
    assert (await post(ready)).status_code == 409
    assert captured == []


async def test_social_speech_is_observation_not_truth_and_beliefs_are_isolated(ready, monkeypatch):
    fake(monkeypatch, action="TALK", participant="MIRINDA", speech="I think the door is locked.")
    response = await post(ready)
    assert response.status_code == 200, response.text
    async with TestSessionLocal() as db:
        state = await db.scalar(select(SessionState).where(SessionState.session_id == "session-1"))
        sim = load(state)
        assert sim.events[0].kind == "SOCIAL" and "said to" in sim.events[0].result
        assert not state.exit_states
        sim.events.append(
            Event(event_id="reply", due=10, kind="SOCIAL", actor="MIRINDA", participant="LILI")
        )
        save(state, sim)
        await db.commit()
    captured = fake(monkeypatch)
    assert (await post(ready)).status_code == 200
    assert "door is locked" in captured[0]["observations"][0]
    assert captured[0]["private_notes"] == {}


async def test_recurring_cycle_is_bounded_and_keeps_backlog(ready, monkeypatch):
    captured = fake(monkeypatch)
    await configure(
        ready,
        deliberation_enabled=True,
        mode="CATCH_UP",
        auto_schedule=True,
        max_decisions_per_run=2,
        max_npcs=2,
    )
    response = await post(ready, "/cycle")
    assert response.status_code == 200, response.text
    assert len(captured) == 2
    assert response.json()["pending_events"] > 0
    assert response.json()["cursor"] <= response.json()["target"]


async def test_real_concordia_engine_uses_one_async_model_call(ready, monkeypatch):
    if not concordia_adapter.available():
        pytest.skip("Optional Concordia extra is not installed.")
    captured = fake(monkeypatch)
    await configure(ready, deliberation_enabled=True, mode="CATCH_UP", decision_engine="concordia")
    response = await post(ready)
    assert response.status_code == 200, response.text
    assert len(captured) == 1


def test_narrator_notes_are_bounded_and_disabled_feature_adds_nothing():
    from types import SimpleNamespace

    from backend.engine.living_world.schema import Settings, Simulation

    sim = Simulation(settings=Settings(living_world_enabled=True, deliberation_enabled=True))
    sim.private_notes = {
        f"NPC{i}": PrivateNotes(goal="g" * 300, belief="b" * 300) for i in range(8)
    }
    state = SimpleNamespace(
        living_world=sim.model_dump(), current_scene_id="START", entity_states={}
    )
    actors = [
        SimpleNamespace(id=key, current_scene_id="START", metadata_json={})
        for key in sim.private_notes
    ]
    text = private_context(state, actors)
    assert len(text) < 2200 and '"npc": "NPC7"' not in text
    assert "belief_unverified" in text
    sim.settings.living_world_enabled = False
    state.living_world = sim.model_dump()
    assert private_context(state, actors) == ""
