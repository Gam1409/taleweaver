"""Lazily compile one recurring slot, never skip unprocessed offline time."""

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.engine.living_world.schema import Event, Simulation
from backend.engine.npc_presence import physically_present
from backend.models.session_state import SessionState
from backend.models.world_entity import WorldEntity


def _unfinished_through(simulation: Simulation, boundary: int) -> bool:
    return any(
        item.status in {"PLANNED", "WAITING_FOR_LLM", "DEFERRED"} and item.due <= boundary
        for item in simulation.events
    )


async def compile_slot(db: AsyncSession, state: SessionState, simulation: Simulation) -> None:
    settings = simulation.settings
    if not settings.auto_schedule or not settings.deliberation_enabled:
        return
    due = max(simulation.cursor, simulation.schedule_next_due)
    if _unfinished_through(simulation, due):
        return
    if due > simulation.target:
        return
    entities = await db.scalars(
        select(WorldEntity)
        .where(
            WorldEntity.session_id == state.session_id,
            WorldEntity.entity_type == "NPC",
        )
        .order_by(WorldEntity.id)
    )
    actors = [
        item.id
        for item in entities
        if physically_present(item, state)
        and not (state.entity_states or {}).get(item.id, {}).get("is_hidden", item.is_hidden)
        and not (state.entity_states or {}).get(item.id, {}).get("is_defeated", False)
    ]
    if not actors:
        return
    # Rotate the bounded cohort between slots instead of starving later NPCs.
    start = (due // settings.schedule_interval_minutes * settings.max_npcs) % len(actors)
    actors = (actors[start:] + actors[:start])[: settings.max_npcs]
    if len(simulation.events) + len(actors) > 512:
        raise HTTPException(
            409,
            "The simulation journal is full. Disable recurring schedules or restore an earlier checkpoint.",
        )
    for actor in actors:
        simulation.events.append(
            Event(
                event_id=f"routine-{due}-{len(simulation.events)}",
                due=due,
                kind="DECISION",
                actor=actor,
            )
        )
    simulation.events.sort(key=lambda event: event.due)
    simulation.schedule_next_due = due + settings.schedule_interval_minutes


def slot_limit(simulation: Simulation) -> int:
    """After compile_slot, reserve a boundary only when unfinished work holds it."""
    if simulation.settings.auto_schedule and simulation.settings.deliberation_enabled:
        boundary = max(simulation.cursor, simulation.schedule_next_due)
        if _unfinished_through(simulation, boundary):
            return min(simulation.target, boundary)
    return simulation.target
