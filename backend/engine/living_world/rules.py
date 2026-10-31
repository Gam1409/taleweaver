"""Deterministic proposals become facts only after canonical world validation."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.engine.living_world.schema import Event
from backend.engine.npc_presence import physically_present
from backend.models.session_state import SessionState
from backend.models.world_entity import WorldEntity, WorldExit, WorldScene


async def npc(db: AsyncSession, state: SessionState, entity_id: str) -> WorldEntity | None:
    result = await db.scalar(
        select(WorldEntity).where(
            WorldEntity.session_id == state.session_id,
            WorldEntity.id == entity_id,
            WorldEntity.entity_type == "NPC",
        )
    )
    return result if isinstance(result, WorldEntity) else None


def location(state: SessionState, entity: WorldEntity) -> str:
    return str(
        (state.entity_states or {})
        .get(entity.id, {})
        .get("current_scene_id", entity.current_scene_id)
    )


def cancel(event: Event, reason: str) -> None:
    event.status = "CANCELLED"
    event.result = reason


async def move(db: AsyncSession, state: SessionState, event: Event, actor: WorldEntity) -> None:
    origin = location(state, actor)
    override = (state.entity_states or {}).get(actor.id, {})
    movable = override.get(
        "moveable", bool(actor.moveable) or str(actor.movement_type).upper() == "MOVABLE"
    )
    allowed = override.get("allowed_scenes", actor.allowed_scenes) or []
    edge = await db.scalar(
        select(WorldExit).where(
            WorldExit.session_id == state.session_id,
            WorldExit.from_scene_id == origin,
            WorldExit.to_scene_id == event.destination,
        )
    )
    destination = await db.scalar(
        select(WorldScene.id).where(
            WorldScene.session_id == state.session_id, WorldScene.id == event.destination
        )
    )
    exit_overrides = state.exit_states or {}
    lock_state = exit_overrides.get(f"{origin}:{event.destination}", {})
    if edge is not None:
        lock_state = {**exit_overrides.get(edge.id, {}), **lock_state}
    if (
        not movable
        or (allowed and event.destination not in allowed)
        or edge is None
        or not destination
        or lock_state.get("is_locked", edge.is_locked)
    ):
        cancel(event, "Movement is not permitted by the current world state.")
        return
    # State overrides are the same authority read by normal gameplay and visual snapshots.
    state.entity_states = {
        **(state.entity_states or {}),
        actor.id: {
            **override,
            "current_scene_id": event.destination,
            "presence": "present",
            "spatial_position": None,
        },
    }
    event.result = f"{actor.name} moved to {event.destination}."


async def apply(db: AsyncSession, state: SessionState, event: Event) -> None:
    if event.kind == "WAIT":
        event.result = "Scheduled waiting period elapsed."
        return
    actor = await npc(db, state, event.actor)
    if actor is None:
        cancel(event, "Actor is unavailable.")
        return
    override = (state.entity_states or {}).get(actor.id, {})
    if (
        override.get("is_hidden", actor.is_hidden)
        or override.get("is_defeated", False)
        or not physically_present(actor, state)
    ):
        cancel(event, "Actor cannot participate.")
        return
    if event.kind == "MOVE":
        await move(db, state, event, actor)
        return
    participant = await npc(db, state, event.participant)
    if (
        participant is None
        or participant.id == actor.id
        or location(state, participant) != location(state, actor)
        or not physically_present(participant, state)
    ):
        cancel(event, "Participants cannot meet at their current locations.")
        return
    other = (state.entity_states or {}).get(participant.id, {})
    if other.get("is_hidden", participant.is_hidden) or other.get("is_defeated", False):
        cancel(event, "Participant is unavailable.")
        return
    event.result = f"{actor.name} and {participant.name} were present together."
