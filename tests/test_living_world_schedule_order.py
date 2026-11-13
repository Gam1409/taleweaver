"""Recurring cohorts respect earlier due slots and bounded unfinished work."""

import json

import pytest
from fastapi import HTTPException
from sqlalchemy import delete, select

from backend.core.config import settings
from backend.core.llm_router import GameMasterLLM
from backend.engine.living_world import runner
from backend.engine.living_world.decisions import Decision
from backend.engine.living_world.schedules import compile_slot, slot_limit
from backend.engine.living_world.schema import Event, Settings, Simulation
from backend.engine.living_world.state import load, save
from backend.engine.memory_rag.scheduling import scheduler
from backend.models.user import User
from backend.models.world_entity import WorldEntity
from tests.living_world_retry_support import retry_world

__all__ = ["retry_world"]
pytestmark = pytest.mark.asyncio


def recurring(events=(), **changes):
    options = {
        "living_world_enabled": True,
        "mode": "CATCH_UP",
        "auto_schedule": True,
        "deliberation_enabled": True,
        "max_npcs": 1,
        "max_decisions_per_run": 1,
    }
    options.update(changes)
    return Simulation(
        settings=Settings(**options),
        cursor=0,
        target=360,
        events=list(events),
    )


async def test_future_explicit_wait_keeps_all_earlier_routines_in_real_cycles(
    retry_world, auth_client, monkeypatch
):
    world = retry_world
    monkeypatch.setattr(settings, "INFERENCE_SERIALIZATION_ENABLED", True)
    monkeypatch.setattr(scheduler, "grace_seconds", 0)
    user = await world.db.scalar(select(User).where(User.username == "test_user"))
    user.llm_settings = {"small_model_provider": "ollama", "small_model": "fixture"}
    sim = recurring([Event(event_id="explicit-wait", due=300, kind="WAIT", actor="GUIDE")])
    save(world.state, sim)
    await world.db.commit()
    contexts = []

    async def decide(self, system, text, model, **kwargs):
        contexts.append(json.loads(text))
        return Decision(
            action="WAIT", goal="Keep the archive orderly.", belief="The workshop is quiet."
        ).model_dump_json()

    monkeypatch.setattr(GameMasterLLM, "aexecute_simple_task", decide)
    base = f"/api/adventures/{world.session_id}/living-world"
    for batch in range(12):
        revision = (await auth_client.get(base)).json()["revision"]
        response = await auth_client.post(base + "/cycle", json={"expected_revision": revision})
        assert response.status_code == 200, response.text
        await world.db.refresh(world.state)
        current = load(world.state)
        routines = [event for event in current.events if event.event_id.startswith("routine-")]
        assert routines and routines[0].due == 0
        if batch == 0:
            assert (
                next(event for event in current.events if event.event_id == "explicit-wait").status
                == "PLANNED"
            )
        if current.status == "COMPLETE":
            break
    assert [event.due for event in routines] == [0, 60, 120, 180, 240, 300, 360]
    assert all(event.status == "COMMITTED" for event in current.events)
    assert current.cursor == current.target == 360
    assert len(contexts) == 7
    assert [context["actor"]["id"] for context in contexts] == [
        "GUIDE",
        "PEER",
        "GUIDE",
        "PEER",
        "GUIDE",
        "PEER",
        "GUIDE",
    ]


@pytest.mark.parametrize("status", ["PLANNED", "WAITING_FOR_LLM", "DEFERRED"])
async def test_unfinished_cohort_remains_the_compilation_barrier_after_reload(retry_world, status):
    world = retry_world
    sim = recurring()
    await compile_slot(world.db, world.state, sim)
    sim.events[0].status = status
    save(world.state, sim)
    await world.db.commit()
    await world.db.refresh(world.state)
    restored = load(world.state)
    before = [event.model_dump() for event in restored.events]
    await compile_slot(world.db, world.state, restored)
    assert [event.model_dump() for event in restored.events] == before
    assert restored.schedule_next_due == 60


@pytest.mark.parametrize("status", ["PLANNED", "WAITING_FOR_LLM", "DEFERRED"])
async def test_unfinished_explicit_boundary_caps_rules_before_future_events(retry_world, status):
    sim = recurring(
        [
            Event(event_id="boundary", due=0, kind="WAIT", status=status),
            Event(event_id="future", due=300, kind="WAIT"),
        ]
    )
    await compile_slot(retry_world.db, retry_world.state, sim)
    assert len(sim.events) == 2
    assert sim.schedule_next_due == 0
    assert slot_limit(sim) == 0
    sim.schedule_next_due = 60
    assert slot_limit(sim) == 60


@pytest.mark.parametrize("unavailable", ["hidden", "absent", "missing"])
async def test_empty_cohort_keeps_explicit_wait_executable_across_actual_cycles(
    retry_world, auth_client, unavailable
):
    world = retry_world
    if unavailable == "missing":
        await world.db.execute(
            delete(WorldEntity).where(WorldEntity.session_id == world.session_id)
        )
    else:
        override = {"is_hidden": True} if unavailable == "hidden" else {"presence": "absent"}
        world.state.entity_states = {actor: dict(override) for actor in ("GUIDE", "PEER")}
    sim = recurring([Event(event_id="explicit", due=300, kind="WAIT")])
    save(world.state, sim)
    await world.db.commit()
    path = f"/api/adventures/{world.session_id}/living-world"
    for _ in range(3):
        status = await auth_client.get(path)
        response = await auth_client.post(
            path + "/cycle", json={"expected_revision": status.json()["revision"]}
        )
        assert response.status_code == 200, response.text
    await world.db.refresh(world.state)
    restored = load(world.state)
    assert len(restored.events) == 1
    assert restored.events[0].status == "COMMITTED"
    assert restored.cursor >= 300
    assert restored.schedule_next_due == 0
    world.inference.assert_not_awaited()


async def test_empty_zero_budget_preserves_due_slot_for_newly_eligible_actor(retry_world):
    world = retry_world
    world.state.entity_states = {actor: {"is_hidden": True} for actor in ("GUIDE", "PEER")}
    sim = recurring([Event(event_id="future", due=300, kind="WAIT")], max_events=0)
    await runner.run(world.db, world.state, sim)
    assert sim.cursor == sim.schedule_next_due == world.state.in_game_time == 0
    assert sim.events[0].status == "PLANNED"
    world.state.entity_states = {"GUIDE": {"is_hidden": False}, "PEER": {"is_hidden": True}}
    sim = load(world.state)
    sim.settings.max_events = 1
    await runner.run(world.db, world.state, sim)
    routines = [event for event in sim.events if event.event_id.startswith("routine-")]
    assert [(event.due, event.actor) for event in routines] == [(0, "GUIDE")]
    assert sim.schedule_next_due == 60
    assert sim.cursor == 0
    assert next(event for event in sim.events if event.event_id == "future").status == "PLANNED"
    world.inference.assert_not_awaited()


@pytest.mark.parametrize("status", ["COMMITTED", "CANCELLED"])
async def test_finished_two_actor_cohort_allows_exactly_the_next_slot(retry_world, status):
    world = retry_world
    sim = recurring(max_npcs=2)
    await compile_slot(world.db, world.state, sim)
    for event in sim.events:
        event.status = status
    await compile_slot(world.db, world.state, sim)
    assert [event.due for event in sim.events] == [0, 0, 60, 60]
    assert [event.actor for event in sim.events] == ["GUIDE", "PEER", "GUIDE", "PEER"]
    assert sim.schedule_next_due == 120
    await compile_slot(world.db, world.state, sim)
    assert len(sim.events) == 4


async def test_low_rules_budget_keeps_unfinished_cohort_without_duplicate_slots(retry_world):
    world = retry_world
    sim = recurring(
        [Event(event_id="future", due=300, kind="WAIT", actor="GUIDE")], max_npcs=2, max_events=1
    )
    await runner.run(world.db, world.state, sim)
    routines = [event for event in sim.events if event.event_id.startswith("routine-")]
    assert [event.due for event in routines] == [0, 0]
    routines[0].status = "COMMITTED"
    save(world.state, sim)
    await world.db.commit()
    await world.db.refresh(world.state)
    sim = load(world.state)
    await runner.run(world.db, world.state, sim)
    assert [event.due for event in sim.events if event.event_id.startswith("routine-")] == [0, 0]
    assert sim.schedule_next_due == 60
    assert sim.cursor == 0
    world.inference.assert_not_awaited()


@pytest.mark.parametrize("disabled", ["auto_schedule", "deliberation_enabled"])
async def test_disabled_scheduling_preserves_ordinary_rules_limit(retry_world, disabled):
    sim = recurring([Event(event_id="future", due=300, kind="WAIT")])
    setattr(sim.settings, disabled, False)
    await compile_slot(retry_world.db, retry_world.state, sim)
    assert len(sim.events) == 1
    assert slot_limit(sim) == 360


@pytest.mark.parametrize(
    "override", [{"is_hidden": True}, {"is_defeated": True}, {"presence": "absent"}]
)
async def test_unavailable_actors_do_not_form_a_routine_cohort(retry_world, override):
    world = retry_world
    world.state.entity_states = {actor: dict(override) for actor in ("GUIDE", "PEER")}
    sim = recurring()
    await compile_slot(world.db, world.state, sim)
    assert sim.events == []
    assert sim.schedule_next_due == 0
    world.inference.assert_not_awaited()


@pytest.mark.parametrize("existing", [510, 511])
async def test_full_cohort_respects_exact_journal_capacity_without_partial_append(
    retry_world, existing
):
    events = [Event(event_id=f"future-{index}", due=1000, kind="WAIT") for index in range(existing)]
    sim = recurring(events, max_npcs=2)
    if existing == 511:
        with pytest.raises(HTTPException) as raised:
            await compile_slot(retry_world.db, retry_world.state, sim)
        assert raised.value.status_code == 409
        assert len(sim.events) == 511
        assert sim.schedule_next_due == 0
    else:
        await compile_slot(retry_world.db, retry_world.state, sim)
        assert len(sim.events) == 512
        assert sim.schedule_next_due == 60


async def test_pause_and_equal_time_dependencies_preserve_clock_and_stable_order(retry_world):
    world = retry_world
    sim = recurring(
        [
            Event(event_id="first", due=0, kind="WAIT", actor="GUIDE"),
            Event(event_id="dependent", due=0, kind="WAIT", actor="PEER", dependencies=["first"]),
            Event(event_id="future", due=300, kind="WAIT", actor="GUIDE"),
        ],
        mode="PAUSE",
        max_events=1,
    )
    await runner.run(world.db, world.state, sim)
    assert sim.events[0].status == "COMMITTED"
    assert sim.events[1].status == "PLANNED"
    await runner.run(world.db, world.state, sim)
    assert sim.events[1].status == "COMMITTED"
    await runner.run(world.db, world.state, sim)
    assert [event.event_id for event in sim.events[:2]] == ["first", "dependent"]
    assert sim.events[2].event_id.startswith("routine-0-")
    assert sim.cursor == world.state.in_game_time == 0
    assert next(event for event in sim.events if event.event_id == "future").status == "PLANNED"
