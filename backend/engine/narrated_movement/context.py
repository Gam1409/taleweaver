"""Expose canonical nearby routes and movement permissions without private NPC memories."""

from typing import Any

from sqlalchemy import select

from backend.engine.npc_movement import allowed_scenes, is_moveable
from backend.engine.npc_presence import presence
from backend.models.world_entity import WorldExit, WorldScene


async def context(manager: Any, rows: list[Any]) -> dict:
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
        if destination in scenes:
            routes.append(
                {"scene_id": destination, "label": scenes[destination], "locked": row.is_locked}
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
