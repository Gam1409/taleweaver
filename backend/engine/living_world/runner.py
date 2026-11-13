"""Bounded rules-only catch-up: commit each event and never fake unavailable reasoning."""

import asyncio
import time
from dataclasses import dataclass

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from backend.engine.living_world import rules
from backend.engine.living_world.schedules import compile_slot, slot_limit
from backend.engine.living_world.schema import Event, Simulation
from backend.engine.living_world.state import save
from backend.models.session_state import SessionState

running: dict[str, asyncio.Event] = {}


def next_event(simulation: Simulation, limit: int) -> Event | None:
    # Stable list order is topological for equal timestamps (validated on import).
    return next(
        iter(
            sorted(
                (
                    event
                    for event in simulation.events
                    if event.status in {"PLANNED", "WAITING_FOR_LLM", "DEFERRED"}
                    and event.due <= limit
                ),
                key=lambda event: event.due,
            )
        ),
        None,
    )


def dependencies_ready(simulation: Simulation, event: Event) -> bool:
    known = {item.event_id: item.status for item in simulation.events}
    if any(known.get(key) == "CANCELLED" for key in event.dependencies):
        rules.cancel(event, "A prerequisite was cancelled.")
        return False
    return all(known.get(key) == "COMMITTED" for key in event.dependencies)


@dataclass
class Budget:
    game_limit: int
    events_left: int
    seconds_left: float
    processed: int = 0

    @classmethod
    def for_simulation(cls, simulation: Simulation) -> "Budget":
        settings = simulation.settings
        return cls(
            simulation.cursor + int(settings.max_catchup_game_hours * 60),
            settings.max_events,
            settings.max_wall_seconds,
        )


async def run(
    db: AsyncSession, state: SessionState, simulation: Simulation, *, budget: Budget | None = None
) -> None:
    if not simulation.settings.living_world_enabled:
        raise HTTPException(409, "Enable Living World first.")
    stop = asyncio.Event()
    running[state.session_id] = stop
    try:
        await _run(db, state, simulation, stop, budget or Budget.for_simulation(simulation))
    finally:
        running.pop(state.session_id, None)


async def _run(
    db: AsyncSession,
    state: SessionState,
    simulation: Simulation,
    stop: asyncio.Event,
    budget: Budget,
) -> None:
    started = time.monotonic()
    settings = simulation.settings
    await compile_slot(db, state, simulation)
    # Reconciliation can skip an empty interval between phases of one cycle.
    # A previously allocated request budget must not rewind that validated cursor.
    limit = max(
        simulation.cursor,
        min(
            slot_limit(simulation),
            simulation.cursor + int(settings.max_catchup_game_hours * 60),
            budget.game_limit,
        ),
    )
    if settings.mode == "PAUSE":
        # Normal play can advance the game clock while connected. Never use UTC
        # or an imported catch-up target to advance a paused world's clock.
        limit = min(limit, max(simulation.cursor, int(state.in_game_time or 0)))
    simulation.last_run_events = 0
    simulation.status = "RUNNING"
    while (
        simulation.last_run_events < min(settings.max_events, budget.events_left)
        and time.monotonic() - started < min(settings.max_wall_seconds, budget.seconds_left)
        and not stop.is_set()
    ):
        event = next_event(simulation, limit)
        if event is None:
            simulation.cursor = limit
            break
        if event.status == "DEFERRED" and event.retry_after > time.time():
            simulation.status = "PARTIAL"
            break
        if not await _process_event(db, state, simulation, event):
            break
        simulation.cursor = max(simulation.cursor, event.due)
        event.committed_at = simulation.cursor
        simulation.last_run_events += 1
        state.in_game_time = max(int(state.in_game_time or 0), simulation.cursor)
        save(state, simulation)
        await db.commit()
    if simulation.status != "WAITING_FOR_LLM":
        simulation.status = (
            "COMPLETE"
            if simulation.cursor >= simulation.target and next_event(simulation, limit) is None
            else "PARTIAL"
        )
    budget.events_left -= simulation.last_run_events
    budget.processed += simulation.last_run_events
    budget.seconds_left = max(0, budget.seconds_left - (time.monotonic() - started))
    simulation.last_run_events = budget.processed
    state.in_game_time = max(int(state.in_game_time or 0), simulation.cursor)
    save(state, simulation)
    await db.commit()


async def _process_event(
    db: AsyncSession, state: SessionState, simulation: Simulation, event: Event
) -> bool:
    if not dependencies_ready(simulation, event):
        if event.status != "CANCELLED":
            simulation.status = "PARTIAL"
            return False
        return True
    if event.kind in {"DECISION", "SOCIAL"}:
        return not await _wait_for_decision(db, state, simulation, event)
    await _apply_rules(db, state, event)
    if event.status != "DEFERRED":
        return True
    save(state, simulation)
    await db.commit()
    simulation.status = "PARTIAL"
    return False


async def _wait_for_decision(
    db: AsyncSession, state: SessionState, simulation: Simulation, event: Event
) -> bool:
    actor = await rules.npc(db, state, event.actor)
    reason = rules.unavailable_reason(state, actor)
    if reason:
        rules.cancel(event, reason, session_id=state.session_id, source_context=state.entity_states)
        return False
    event.status = "WAITING_FOR_LLM"
    simulation.status = "WAITING_FOR_LLM"
    return True


async def _apply_rules(db: AsyncSession, state: SessionState, event: Event) -> None:
    if event.status == "DEFERRED":
        event.status = "PLANNED"
    await rules.apply(db, state, event)
    if event.status not in {"CANCELLED", "DEFERRED"}:
        event.status = "COMMITTED"
