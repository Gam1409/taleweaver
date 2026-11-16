"""Living World retries, reverse routes and stale queued actors persist canonical outcomes."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from backend.engine.living_world import deliberation, interaction, rules, runner
from backend.engine.living_world.decision_context import context_for, destinations
from backend.engine.living_world.decisions import Decision
from backend.engine.living_world.schedules import compile_slot
from backend.engine.living_world.schema import Event
from backend.engine.living_world.state import load, public_status, save
from backend.models import ChatMessage
from tests.conftest import TestSessionLocal
from tests.living_world_retry_support import (
    actor,
    configure_reverse_route,
    current_state,
    retry_world,
    simulation,
)

__all__ = ["retry_world"]
pytestmark = pytest.mark.asyncio


async def _deferred(world):
    world.db.add(
        ChatMessage(
            id="recent-reply",
            session_id=world.session_id,
            role="assistant",
            scene_id="A",
            content="The keeper is still talking.",
            created_at=datetime.now(timezone.utc),
        )
    )
    await world.db.commit()
    sim = simulation(
        [Event(event_id="departure", due=5, kind="MOVE", actor="GUIDE", destination="B")]
    )
    await runner.run(world.db, world.state, sim)
    assert sim.events[0].status == "DEFERRED" and sim.events[0].deferrals == 1
    return sim


async def _permit_retry(db, state):
    message = await db.get(ChatMessage, "recent-reply")
    message.created_at = datetime.now(timezone.utc) - timedelta(minutes=10)
    sim = load(state)
    sim.events[0].retry_after = 0
    save(state, sim)
    await db.commit()
    return sim


async def test_deferred_retry_commits_position_event_cursor_and_observation_once(retry_world):
    world = retry_world
    await _deferred(world)
    async with TestSessionLocal() as db:
        state = await current_state(db, world.session_id)
        sim = await _permit_retry(db, state)
        await runner.run(db, state, sim)
    async with TestSessionLocal() as db:
        state = await current_state(db, world.session_id)
        sim = load(state)
        event = sim.events[0]
        assert rules.location(state, await actor(db, world.session_id)) == "B"
        assert event.status == "COMMITTED" and event.committed_at == 5
        assert event.deferrals == 1 and sim.cursor == state.in_game_time == sim.target == 10
        assert public_status(sim)["recap"] == ["Guide moved to B."]
        later = await context_for(
            db, state, sim, Event(event_id="later", due=11, kind="DECISION", actor="GUIDE")
        )
        assert later["observations"] == ["Guide moved to B."]
        before = deepcopy(event.model_dump())
        await runner.run(db, state, sim)
        assert sim.events[0].model_dump() == before and sim.last_run_events == 0
        assert public_status(sim)["recap"] == ["Guide moved to B."]
        assert "Private goal" not in str(public_status(sim))
    world.inference.assert_not_awaited()


async def test_retry_commit_failure_does_not_persist_movement_without_event(
    retry_world, monkeypatch
):
    world = retry_world
    await _deferred(world)
    async with TestSessionLocal() as db:
        state = await current_state(db, world.session_id)
        sim = await _permit_retry(db, state)
        original = db.commit

        async def fail():
            raise RuntimeError("Synthetic interrupted commit")

        monkeypatch.setattr(db, "commit", fail)
        with pytest.raises(RuntimeError, match="interrupted commit"):
            await runner.run(db, state, sim)
        await db.rollback()
        monkeypatch.setattr(db, "commit", original)
    async with TestSessionLocal() as db:
        state = await current_state(db, world.session_id)
        sim = load(state)
        assert rules.location(state, await actor(db, world.session_id)) == "A"
        assert sim.events[0].status == "DEFERRED" and sim.cursor == 0
        await runner.run(db, state, sim)
        assert sim.events[0].status == "COMMITTED"
    world.inference.assert_not_awaited()


async def test_repeated_scene_deferrals_keep_the_existing_limit(retry_world):
    world = retry_world
    sim = await _deferred(world)
    for attempt in range(2, interaction.MAX_DEFERRALS + 1):
        sim.events[0].retry_after = 0
        await runner.run(world.db, world.state, sim)
        assert sim.events[0].deferrals == attempt
    assert sim.events[0].status == "CANCELLED"
    assert rules.location(world.state, await actor(world.db, world.session_id)) == "A"
    assert "moved to B" not in str(public_status(sim))


@pytest.mark.parametrize(
    "blocked",
    [
        None,
        "one_way",
        "row_lock",
        "id_lock",
        "stored_pair",
        "reverse_pair",
        "allowed",
        "exit_script",
        "open_script",
        "enter_script",
        "leave_script",
        "guard",
        "rule",
        "foreign",
    ],
)
async def test_reverse_route_context_and_execution_share_stored_permissions(retry_world, blocked):
    world = retry_world
    db, state, edge = world.db, world.state, world.edge
    origin = await configure_reverse_route(world, blocked)
    choices = await destinations(db, state, await actor(db, world.session_id), origin)
    assert ("A" in choices) is (blocked is None)
    sim = simulation([Event(event_id="return", due=5, kind="MOVE", actor="GUIDE", destination="A")])
    await runner.run(db, state, sim)
    async with TestSessionLocal() as saved_db:
        saved = await current_state(saved_db, world.session_id)
        event = load(saved).events[0]
        assert event.status == ("COMMITTED" if blocked is None else "CANCELLED")
        assert rules.location(saved, await actor(saved_db, world.session_id)) == (
            "A" if blocked is None else "B"
        )
    assert (edge.from_scene_id, edge.to_scene_id) == ("A", "B")
    world.inference.assert_not_awaited()


@pytest.mark.parametrize("kind", ["DECISION", "SOCIAL"])
@pytest.mark.parametrize(
    "unavailable", ["removed", "absent", "audible", "hidden", "defeated", "authored_hidden"]
)
async def test_unavailable_queued_actor_cancels_without_stalling_later_rules(
    retry_world, kind, unavailable
):
    world = retry_world
    row = await actor(world.db, world.session_id)
    if unavailable == "removed":
        await world.db.delete(row)
    elif unavailable == "authored_hidden":
        row.is_hidden = True
    else:
        change = (
            {"presence": unavailable}
            if unavailable in {"absent", "audible"}
            else {"is_hidden" if unavailable == "hidden" else "is_defeated": True}
        )
        world.state.entity_states = {"GUIDE": change}
    await world.db.commit()
    sim = simulation(
        [
            Event(
                event_id="unavailable",
                due=2,
                kind=kind,
                actor="GUIDE",
                participant="PEER" if kind == "SOCIAL" else "",
            ),
            Event(event_id="dependent", due=3, kind="WAIT", dependencies=["unavailable"]),
            Event(event_id="later", due=4, kind="WAIT"),
        ]
    )
    await runner.run(world.db, world.state, sim)
    async with TestSessionLocal() as db:
        state = await current_state(db, world.session_id)
        saved = load(state)
        assert [event.status for event in saved.events] == ["CANCELLED", "CANCELLED", "COMMITTED"]
        assert saved.events[0].attempts == 0 and saved.deliberation_attempts == 0
        assert saved.status == "COMPLETE" and saved.cursor == state.in_game_time == 10
        assert not saved.private_notes and public_status(saved)["pending_events"] == 0
    world.inference.assert_not_awaited()


async def test_recurring_cohort_survives_actor_departures_between_batches(retry_world):
    world = retry_world
    sim = simulation([], auto_schedule=True, deliberation_enabled=True, max_npcs=2)
    await compile_slot(world.db, world.state, sim)
    assert len(sim.events) == 2
    sim.events.append(Event(event_id="later", due=5, kind="WAIT"))
    save(world.state, sim)
    world.state.entity_states = {"GUIDE": {"presence": "absent"}, "PEER": {"is_hidden": True}}
    await world.db.commit()
    await runner.run(world.db, world.state, load(world.state))
    async with TestSessionLocal() as db:
        state = await current_state(db, world.session_id)
        saved = load(state)
        assert [event.status for event in saved.events] == ["CANCELLED", "CANCELLED", "COMMITTED"]
        assert saved.schedule_next_due == 60 and saved.status == "COMPLETE"
        assert public_status(saved)["llm_calls"] == 0
    world.inference.assert_not_awaited()


@pytest.mark.parametrize("change", ["presence", "removed"])
async def test_prepared_actor_changes_keep_late_result_fencing_and_queue_recovery(
    retry_world, monkeypatch, change
):
    world = retry_world
    sim = simulation(
        [
            Event(event_id="choice", due=5, kind="DECISION", actor="GUIDE"),
            Event(event_id="later", due=6, kind="WAIT"),
        ],
        deliberation_enabled=True,
    )
    monkeypatch.setattr(deliberation, "require_enabled", lambda *_: None)
    prepared = await deliberation.prepare(world.db, world.state, sim, SimpleNamespace())
    async with TestSessionLocal() as db:
        state = await current_state(db, world.session_id)
        if change == "presence":
            state.entity_states = {"GUIDE": {"presence": "absent"}}
        else:
            await db.delete(await actor(db, world.session_id))
        await db.commit()
    async with TestSessionLocal() as db:
        state = await current_state(db, world.session_id)
        current = load(state)
        with pytest.raises(HTTPException) as caught:
            await deliberation.apply(
                db,
                state,
                current,
                prepared,
                Decision(action="WAIT", goal="Private new goal.", belief="Private new belief."),
            )
        assert caught.value.status_code == 409
        assert not load(state).private_notes
        await runner.run(db, state, load(state))
        assert [event.status for event in load(state).events] == ["CANCELLED", "COMMITTED"]
    world.inference.assert_not_awaited()
