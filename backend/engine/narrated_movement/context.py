"""Expose canonical nearby routes and movement permissions without private NPC memories."""

from collections.abc import Sequence
from typing import Any

from sqlalchemy import select

from backend.engine.living_world.routes import lock_state
from backend.engine.npc_movement import allowed_scenes, is_moveable
from backend.engine.npc_presence import presence
from backend.models.world_entity import WorldExit, WorldScene


async def context(manager: Any, rows: list[Any], *, exit_updates: Sequence[Any] = ()) -> dict:
    scene_id = manager.state.current_scene_id
    scenes = {
        scene.id: scene.label
        for scene in await manager.db.scalars(
            select(WorldScene).where(WorldScene.session_id == manager.state.session_id)
        )
    }
    exits = await manager.db.scalars(
        select(WorldExit).where(WorldExit.session_id == manager.state.session_id)
    )
    routes = []
    for row in exits:
        destination = _destination(row, scene_id)
        if destination is not None and destination in scenes:
            routes.append(
                {
                    "scene_id": destination,
                    "label": scenes[destination],
                    "locked": _locked(manager.state, row, scene_id, destination, exit_updates),
                }
            )
    open_routes = {row["scene_id"] for row in routes if not row["locked"]}
    actors = {
        "__player__": {
            "id": "__player__",
            "can_move": True,
            "presence": "present",
            "allowed_destinations": sorted(open_routes),
        }
    }
    for entity in rows:
        actor = _actor(manager.state, entity, open_routes)
        if actor is not None:
            actors[entity.id] = actor
    return {
        "scene_id": scene_id,
        "routes": sorted(routes, key=lambda row: (row["scene_id"], row["locked"])),
        "actors": actors,
    }


def _locked(state: Any, edge: Any, origin: str, target: str, updates: Sequence[Any]) -> bool:
    effective = lock_state(state, edge, origin, target).get("is_locked")
    locked = effective if isinstance(effective, bool) else edge.is_locked
    for update in updates:
        direct = (update.from_scene_id, update.to_scene_id) == (
            edge.from_scene_id,
            edge.to_scene_id,
        )
        reverse = edge.exit_type == "bidirectional" and (
            update.from_scene_id,
            update.to_scene_id,
        ) == (edge.to_scene_id, edge.from_scene_id)
        if direct or reverse:
            locked = update.is_locked
    return locked


def _destination(row: WorldExit, scene_id: str) -> str | None:
    if row.from_scene_id == scene_id:
        return row.to_scene_id
    if row.to_scene_id == scene_id and row.exit_type == "bidirectional":
        return row.from_scene_id
    return None


def _actor(state: Any, entity: Any, routes: set[str]) -> dict | None:
    override = (state.entity_states or {}).get(entity.id, {})
    if (
        entity.entity_type != "NPC"
        or override.get("current_scene_id", entity.current_scene_id) != state.current_scene_id
        or override.get("is_hidden", entity.is_hidden)
        or override.get("is_defeated", getattr(entity, "is_defeated", False))
    ):
        return None
    can_move = is_moveable(entity, override)
    allowed = allowed_scenes(entity, state.entity_states or {})
    permitted = (
        {route for route in routes if route.casefold() in {value.casefold() for value in allowed}}
        if allowed
        else routes
    )
    return {
        "id": entity.id,
        "name": override.get("name", entity.name),
        "can_move": can_move,
        "presence": presence(entity, state),
        "allowed_destinations": sorted(permitted if can_move else []),
    }
