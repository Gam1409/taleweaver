"""Bounded rules-only catch-up: commit each event and never fake unavailable reasoning."""

import asyncio
import time

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from backend.engine.living_world import rules
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
                    if event.status in {"PLANNED", "WAITING_FOR_LLM"} and event.due <= limit
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


async def run(db: AsyncSession, state: SessionState, simulation: Simulation) -> None:
    if not simulation.settings.living_world_enabled:
        raise HTTPException(409, "Enable Living World first.")
    stop = asyncio.Event()
    running[state.session_id] = stop
    try:
        await _run(db, state, simulation, stop)
    finally:
        running.pop(state.session_id, None)


async def _run(
    db: AsyncSession, state: SessionState, simulation: Simulation, stop: asyncio.Event
) -> None:
    started = time.monotonic()
    settings = simulation.settings
    limit = min(simulation.target, simulation.cursor + int(settings.max_catchup_game_hours * 60))
    if settings.mode == "PAUSE":
        # Normal play can advance the game clock while connected. Never use UTC
        # or an imported catch-up target to advance a paused world's clock.
        limit = min(limit, max(simulation.cursor, int(state.in_game_time or 0)))
    simulation.last_run_events = 0
    simulation.status = "RUNNING"
    while (
        simulation.last_run_events < settings.max_events
        and time.monotonic() - started < settings.max_wall_seconds
        and not stop.is_set()
    ):
        event = next_event(simulation, limit)
        if event is None:
            simulation.cursor = limit
            break
        if not dependencies_ready(simulation, event):
            if event.status != "CANCELLED":
                simulation.status = "PARTIAL"
                break
        elif event.kind in {"DECISION", "SOCIAL"}:
            event.status = "WAITING_FOR_LLM"
            simulation.status = "WAITING_FOR_LLM"
            break
        else:
            await rules.apply(db, state, event)
            event.status = "CANCELLED" if event.status == "CANCELLED" else "COMMITTED"
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
    state.in_game_time = max(int(state.in_game_time or 0), simulation.cursor)
    save(state, simulation)
    await db.commit()
