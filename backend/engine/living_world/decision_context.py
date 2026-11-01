"""NPC-local evidence and an exact state fence for asynchronous deliberation."""

import hashlib
import json
from typing import Any

from fastapi import HTTPException
from sqlalchemy import inspect, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.engine.living_world import rules
from backend.engine.living_world.schema import Event, Simulation
from backend.engine.npc_movement import allowed_scenes
from backend.engine.npc_presence import physically_present
from backend.engine.personality.profile import personality_context
from backend.models.session_state import SessionState
from backend.models.world_entity import WorldEntity, WorldExit, WorldScene


def fingerprint(state: SessionState, context: dict[str, Any]) -> str:
    values = {col.key: getattr(state, col.key) for col in inspect(SessionState).columns}
    text = json.dumps([values, context], sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha256(text.encode()).hexdigest()


async def context_for(
    db: AsyncSession, state: SessionState, simulation: Simulation, event: Event
) -> dict[str, Any]:
    actor = await rules.npc(db, state, event.actor)
    if actor is None:
        raise HTTPException(409, "The decision actor is unavailable.")
    override = (state.entity_states or {}).get(actor.id, {})
    if (
        not physically_present(actor, state)
        or override.get("is_hidden", actor.is_hidden)
        or override.get("is_defeated", False)
    ):
        raise HTTPException(409, "The decision actor cannot participate.")
    location = rules.location(state, actor)
    scene = await db.scalar(
        select(WorldScene).where(
            WorldScene.session_id == state.session_id, WorldScene.id == location
        )
    )
    observations = [
        item.result
        for item in simulation.events
        if item.status == "COMMITTED"
        and item.kind in {"MOVE", "MEET", "SOCIAL"}
        and event.actor in {item.actor, item.participant}
        and item.due <= event.due
    ][-8:]
    notes = simulation.private_notes.get(actor.id)
    return {
        "actor": {
            "id": actor.id,
            "name": str(actor.name)[:100],
            "description": str(actor.description or "")[:1000],
            "authored_character": str(getattr(actor, "character", "") or "")[:300],
            "authored_goal": str(getattr(actor, "goal", "") or "")[:300],
            "personality_tendencies": personality_context(actor),
        },
        "scene": {
            "id": location,
            "description": str(scene.description or "")[:1000] if scene else "",
        },
        "minute": event.due,
        "event_kind": event.kind,
        "participants": await participants(db, state, actor.id, location, event),
        "observations": observations,
        "private_notes": notes.model_dump(exclude={"observations"}) if notes else {},
        "destinations": await destinations(db, state, actor, scene),
    }


async def destinations(db: AsyncSession, state: SessionState, actor: Any, scene: Any) -> list[str]:
    override = (state.entity_states or {}).get(actor.id, {})
    movable = override.get(
        "moveable", bool(actor.moveable) or str(actor.movement_type).upper() == "MOVABLE"
    )
    if not movable or scene is None or scene.on_leave_scene_script:
        return []
    allowed = allowed_scenes(actor, state.entity_states or {})
    rows = await db.execute(
        select(WorldExit, WorldScene)
        .join(
            WorldScene,
            (WorldScene.id == WorldExit.to_scene_id)
            & (WorldScene.session_id == WorldExit.session_id),
        )
        .where(WorldExit.session_id == state.session_id, WorldExit.from_scene_id == scene.id)
        .order_by(WorldExit.id)
    )
    return [edge.to_scene_id for edge, target in rows if permitted(state, edge, target, allowed)][
        :16
    ]


def permitted(state: SessionState, edge: WorldExit, target: WorldScene, allowed: list) -> bool:
    overrides = state.exit_states or {}
    lock = {
        **overrides.get(edge.id, {}),
        **overrides.get(f"{edge.from_scene_id}:{edge.to_scene_id}", {}),
    }
    return not (
        lock.get("is_locked", edge.is_locked)
        or (allowed and target.id not in allowed)
        or edge.on_exit_used_script
        or edge.on_open_exit_script
        or target.on_enter_scene_script
        or edge.rule_to_unlock
        or edge.unlock_expression
    )


async def participants(
    db: AsyncSession, state: SessionState, actor_id: str, location: str, event: Event
) -> list[dict[str, str]]:
    entities = await db.scalars(
        select(WorldEntity)
        .where(
            WorldEntity.session_id == state.session_id,
            WorldEntity.entity_type == "NPC",
            WorldEntity.id != actor_id,
        )
        .order_by(WorldEntity.id)
    )
    return [
        {"id": item.id, "name": str(item.name)[:100]}
        for item in entities
        if (event.kind != "SOCIAL" or item.id == event.participant)
        and rules.location(state, item) == location
        and physically_present(item, state)
        and not (state.entity_states or {}).get(item.id, {}).get("is_hidden", item.is_hidden)
        and not (state.entity_states or {}).get(item.id, {}).get("is_defeated", False)
    ][:8]
