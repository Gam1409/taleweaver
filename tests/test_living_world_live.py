"""Automatic batches use real SQL and controlled model replies."""

import asyncio

import pytest_asyncio

from backend.engine.living_world import live
from backend.engine.living_world.schema import Simulation
from backend.engine.memory_rag.scheduling import scheduler
from tests import test_living_world_decisions as decisions
from tests.conftest import TestSessionLocal

world, ready = decisions.world, decisions.ready
BASE = decisions.BASE


@pytest_asyncio.fixture(autouse=True)
async def clean_runtime(monkeypatch):
    monkeypatch.setattr(live, "AsyncSessionLocal", TestSessionLocal)
    await live.shutdown()
    yield
    await live.shutdown()


async def enable(client, **overrides):
    current = (await client.get(BASE)).json()
    result = await client.patch(
        BASE,
        json={
            "expected_revision": current["revision"],
            "settings": {**current["settings"], "live_enabled": True, **overrides},
        },
    )
    assert result.status_code == 200, result.text


async def beat(client):
    result = await client.post(BASE + "/presence", json={"client_id": "tab", "active": True})
    assert result.status_code == 200, result.text
    task = live.runtimes.get("session-1")
    if task and task.task:
        await asyncio.wait_for(asyncio.shield(task.task), 5)


async def test_heartbeat_runs_decision_without_manual_button(ready, monkeypatch):
    calls = decisions.fake(monkeypatch)
    await enable(ready)
    await beat(ready)
    result = (await ready.get(BASE)).json()
    assert result["llm_calls"] == 1 and len(calls) == 1
    assert not result["live_paused"] and not result["live_running"]
    await beat(ready)
    assert len(calls) == 1  # Interval and one task per session.


async def test_disabled_and_foreground_activity_do_not_launch(ready, monkeypatch):
    calls = decisions.fake(monkeypatch)
    await beat(ready)
    assert not calls
    await enable(ready)
    async with scheduler.foreground():
        await beat(ready)
    assert not calls


async def test_stop_pauses_automatic_work_until_explicit_retry(ready, monkeypatch):
    calls = decisions.fake(monkeypatch)
    await enable(ready)
    await beat(ready)
    await ready.post(BASE + "/stop")
    live.runtimes["session-1"].next_check = 0
    await beat(ready)
    assert len(calls) == 1
    assert (await ready.get(BASE)).json()["live_paused"]


async def test_model_failure_pauses_instead_of_retrying_each_heartbeat(ready, monkeypatch):
    from backend.core.llm_router import GameMasterLLM

    async def fail(*args, **kwargs):
        raise ValueError("controlled failure")

    monkeypatch.setattr(GameMasterLLM, "aexecute_simple_task", fail)
    await enable(ready)
    await beat(ready)
    current = (await ready.get(BASE)).json()
    assert current["live_paused"] and current["live_error"]
    live.runtimes["session-1"].next_check = 0
    await beat(ready)
    assert (await ready.get(BASE)).json()["llm_calls"] == 1


def test_live_clock_does_not_advance_from_reading_time():
    simulation = Simulation()
    assert not live.due(simulation)
    assert not live.active({"clients": {"old": {"active": True, "seen": 1}}})
