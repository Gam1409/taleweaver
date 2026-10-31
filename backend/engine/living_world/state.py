"""Clocks, public projections and snapshot lifecycle; no I/O or model calls."""

from typing import Any
from uuid import uuid4

from backend.engine.living_world.schema import Simulation


def load(state: Any) -> Simulation:
    raw = getattr(state, "living_world", None)
    if raw is not None:
        return Simulation.model_validate(raw)
    return Simulation(cursor=int(state.in_game_time or 0), target=int(state.in_game_time or 0))


def save(state: Any, simulation: Simulation) -> None:
    simulation.revision += 1
    state.living_world = simulation.model_dump(mode="json")


def offline_total(presence: dict | None) -> float:
    return float((presence or {}).get("offline_total", 0))


def reconcile(simulation: Simulation, world_time: int, presence: dict | None) -> None:
    """Consume cumulative UTC absence once; PAUSE discards it without advancing time."""
    total = offline_total(presence)
    elapsed = max(0, total - simulation.offline_total_seen)
    simulation.offline_total_seen = max(total, simulation.offline_total_seen)
    pending = any(
        event.status in {"PLANNED", "WAITING_FOR_LLM"} and event.due <= world_time
        for event in simulation.events
    )
    if not pending:
        simulation.cursor = max(simulation.cursor, world_time)
    simulation.target = max(simulation.target, simulation.cursor, world_time)
    if simulation.settings.mode == "CATCH_UP" and simulation.settings.living_world_enabled:
        minutes = (
            elapsed * simulation.settings.offline_time_scale / 60 + simulation.fractional_minutes
        )
        whole = int(minutes)
        simulation.fractional_minutes = minutes - whole
        simulation.target += whole
        if simulation.target > simulation.cursor and simulation.status != "WAITING_FOR_LLM":
            simulation.status = "PARTIAL"
    else:
        simulation.status = "PAUSED"


def fork(raw: dict | None, *, absence_total: float = 0) -> dict | None:
    if raw is None:
        return None
    simulation = Simulation.model_validate(raw)
    simulation.timeline = str(uuid4())
    simulation.revision += 1
    simulation.offline_total_seen = absence_total
    simulation.status = "PAUSED"
    return simulation.model_dump(mode="json")


def public_status(simulation: Simulation) -> dict:
    return {
        "settings": simulation.settings.model_dump(),
        "revision": simulation.revision,
        "status": simulation.status,
        "cursor": simulation.cursor,
        "target": simulation.target,
        "pending_events": sum(
            event.status in {"PLANNED", "WAITING_FOR_LLM"} for event in simulation.events
        ),
        "last_run_events": simulation.last_run_events,
        "llm_calls": 0,
        "tokens": 0,
        "recap": [
            event.result
            for event in simulation.events
            if event.status == "COMMITTED" and event.observed_by_player
        ][-20:],
        "capabilities": ["PAUSE", "RULES_CATCH_UP"],
    }
