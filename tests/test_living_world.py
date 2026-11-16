"""Offline clocks, causal barriers and atomic local rules work without a GPU."""

from copy import deepcopy

import pytest
from sqlalchemy import select

from backend.engine.living_world.presence import heartbeat
from backend.engine.living_world.runner import run
from backend.engine.living_world.schema import Event, Settings, Simulation
from backend.engine.living_world.state import fork, load, public_status, reconcile
from backend.models.session_state import SessionState
from backend.models.world_entity import WorldEntity, WorldExit, WorldScene
from tests.conftest import TestSessionLocal
from tests.test_game_loop import _seed_game_context

HOURS_72 = 72 * 3600


def absent_presence():
    presence = heartbeat(None, "tab-a", True, 1000)
    presence = heartbeat(presence, "tab-a", False, 1010)
    return heartbeat(presence, "tab-a", True, 1010 + HOURS_72)


def test_pause_does_not_convert_real_absence_or_modify_queued_events():
    sim = Simulation(
        settings=Settings(living_world_enabled=True),
        events=[Event(event_id="later", due=50, kind="WAIT")],
    )
    before = sim.events[0].model_dump()
    reconcile(sim, 0, absent_presence())
    assert sim.cursor == sim.target == 0
    assert sim.events[0].model_dump() == before


def test_offline_time_is_consumed_once_with_fractional_remainder_and_multiple_tabs():
    sim = Simulation(settings=Settings(living_world_enabled=True, mode="CATCH_UP"))
    presence = absent_presence()
    reconcile(sim, 0, presence)
    assert sim.target == 4320 and sim.cursor == 0
    reconcile(sim, 0, presence)
    assert sim.target == 4320
    presence = heartbeat(presence, "tab-b", True, 1011 + HOURS_72)
    presence = heartbeat(presence, "tab-a", False, 1012 + HOURS_72)
    presence = heartbeat(presence, "tab-b", True, 1013 + HOURS_72)
    assert presence["offline_total"] == HOURS_72
    reconcile(sim, 0, {"offline_total": HOURS_72 + 30})
    assert sim.fractional_minutes == 0.5
    reconcile(sim, 0, {"offline_total": HOURS_72 + 60})
    assert sim.target == 4321 and sim.fractional_minutes == 0


def test_crashed_browser_uses_one_presence_grace_and_clock_regression_never_adds_time():
    p = heartbeat(None, "first", True, 100)
    p = heartbeat(p, "second", True, 100 + HOURS_72)
    assert p["offline_total"] == HOURS_72 - 60
    before = p["offline_total"]
    p = heartbeat(p, "second", True, 50)
    assert p["offline_total"] == before


def test_duplicate_close_does_not_extend_offline_baseline():
    p = heartbeat(None, "tab", True, 100)
    p = heartbeat(p, "tab", False, 110)
    p = heartbeat(p, "tab", False, 120)
    p = heartbeat(p, "tab", True, 180)
    assert p["offline_total"] == 70


def test_invalid_settings_and_causal_cycles_are_rejected():
    from pydantic import ValidationError

    for value in (-1, float("inf"), float("nan")):
        with pytest.raises(ValidationError):
            Settings(offline_time_scale=value)
    with pytest.raises(ValidationError):
        Simulation(events=[Event(event_id="a", due=0, kind="WAIT", dependencies=["a"])])


def test_fork_keeps_local_queue_but_isolates_timeline_and_presence_accounting():
    sim = Simulation(
        cursor=10,
        target=100,
        events=[Event(event_id="secret", due=20, kind="DECISION", actor="Private actor")],
    )
    raw = sim.model_dump(mode="json")
    copy = fork(raw, absence_total=500)
    assert copy["timeline"] != raw["timeline"]
    assert copy["events"] == raw["events"]
    assert copy["offline_total_seen"] == 500
    assert "Private actor" not in str(public_status(sim))
    assert "secret" not in str(public_status(sim))


async def seed(db):
    user, _, _, state = await _seed_game_context(db)
    db.add_all(
        [
            WorldScene(
                session_id=state.session_id, id="START", label="Hall", description="A public hall."
            ),
            WorldScene(
                session_id=state.session_id, id="ROOM", label="Room", description="A private room."
            ),
        ]
    )
    db.add(
        WorldExit(
            session_id=state.session_id,
            from_scene_id="START",
            to_scene_id="ROOM",
            label="Door",
            is_locked=False,
        )
    )
    for npc_id in ("LILI", "MIRINDA"):
        db.add(
            WorldEntity(
                session_id=state.session_id,
                id=npc_id,
                entity_type="NPC",
                name=npc_id,
                description="An adult resident with an independent daily routine.",
                current_scene_id="START",
                moveable=True,
                allowed_scenes=["START", "ROOM"],
                is_hidden=False,
            )
        )
    await db.commit()
    return user, state


def demo():
    return Simulation(
        settings=Settings(living_world_enabled=True, mode="CATCH_UP"),
        target=4320,
        events=[
            Event(event_id="lili-move", due=60, kind="MOVE", actor="LILI", destination="ROOM"),
            Event(
                event_id="mirinda-move", due=90, kind="MOVE", actor="MIRINDA", destination="ROOM"
            ),
            Event(
                event_id="meet",
                due=120,
                kind="MEET",
                actor="LILI",
                participant="MIRINDA",
                dependencies=["lili-move", "mirinda-move"],
            ),
        ],
    )


async def test_rules_demo_is_atomic_bounded_repeatable_and_does_not_reveal_offscreen_events():
    async with TestSessionLocal() as db:
        _, state = await seed(db)
        sim = demo()
        await run(db, state, sim)
        assert sim.cursor == state.in_game_time == 360
        assert sim.target == 4320 and sim.status == "PARTIAL"
        assert [event.status for event in sim.events] == ["COMMITTED"] * 3
        assert state.entity_states["LILI"]["current_scene_id"] == "ROOM"
        assert public_status(sim)["recap"] == []
        before = deepcopy([event.model_dump() for event in sim.events])
        await run(db, state, load(state))
        assert [event.model_dump() for event in load(state).events] == before
        assert state.in_game_time == 720
        assert load(state).last_run_events == 0


async def test_unavailable_reasoning_blocks_cursor_and_dependent_actions_without_calls():
    async with TestSessionLocal() as db:
        _, state = await seed(db)
        sim = demo()
        sim.events = [
            Event(event_id="decision", due=10, kind="DECISION", actor="LILI"),
            *sim.events,
        ]
        await run(db, state, sim)
        assert sim.status == "WAITING_FOR_LLM"
        assert sim.cursor == state.in_game_time == 0
        assert sim.events[1].status == "PLANNED"
        assert public_status(sim)["llm_calls"] == 0


async def test_incompatible_locations_cancel_meeting_instead_of_inventing_a_conversation():
    async with TestSessionLocal() as db:
        _, state = await seed(db)
        sim = demo()
        sim.events = [
            sim.events[0],
            sim.events[2].model_copy(update={"dependencies": ["lili-move"]}),
        ]
        await run(db, state, sim)
        assert sim.events[1].status == "CANCELLED"
        assert "cannot meet" in sim.events[1].result


@pytest.mark.parametrize("key_kind", ["id", "pair"])
async def test_movement_respects_runtime_door_locks(key_kind):
    async with TestSessionLocal() as db:
        _, state = await seed(db)
        edge = await db.scalar(select(WorldExit).where(WorldExit.session_id == "session-1"))
        key = edge.id if key_kind == "id" else "START:ROOM"
        state.exit_states = {key: {"is_locked": True}}
        sim = demo()
        await run(db, state, sim)
        assert all(event.status == "CANCELLED" for event in sim.events)
        assert state.entity_states.get("LILI", {}).get("current_scene_id", "START") == "START"


async def test_zero_budget_does_not_advance_and_equal_time_dependencies_follow_causal_order():
    async with TestSessionLocal() as db:
        _, state = await seed(db)
        sim = demo()
        sim.settings.max_events = 0
        await run(db, state, sim)
        assert state.in_game_time == sim.cursor == 0
        sim.settings.max_events = 2
        sim.events = [
            Event(event_id="z", due=10, kind="WAIT"),
            Event(event_id="a", due=10, kind="WAIT", dependencies=["z"]),
        ]
        await run(db, state, sim)
        assert all(event.status == "COMMITTED" for event in sim.events)


async def test_failure_between_event_commits_can_resume_without_reapplying_first_event(monkeypatch):
    async with TestSessionLocal() as db:
        _, state = await seed(db)
        sim = demo()
        original_commit = db.commit
        calls = 0

        async def crash():
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError("Simulated process failure before commit")
            await original_commit()

        monkeypatch.setattr(db, "commit", crash)
        with pytest.raises(RuntimeError, match="Simulated process failure"):
            await run(db, state, sim)
        await db.rollback()
    async with TestSessionLocal() as db:
        state = await db.scalar(select(SessionState).where(SessionState.session_id == "session-1"))
        sim = load(state)
        assert sim.cursor == 60
        assert sim.events[0].status == "COMMITTED" and sim.events[1].status == "PLANNED"
        await run(db, state, sim)
        assert sim.last_run_events == 2
        assert all(event.status == "COMMITTED" for event in sim.events)
