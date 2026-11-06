"""Keep session maps and canonical item definitions consistent with checkpoint state."""

from copy import deepcopy
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.session_state import SessionState
from backend.models.world_entity import WorldEntity
from backend.models.world_map import WorldMap

_IMMUTABLE = {"pk", "id", "template_id", "session_id", "created_at", "updated_at"}
_ITEM_FIELDS = {column.name for column in WorldEntity.__table__.columns} - _IMMUTABLE


def validate(snapshot: dict) -> None:
    if "world_map" in snapshot:
        maps = snapshot["world_map"]
        if not isinstance(maps, list) or any(not _valid_map(raw) for raw in maps):
            raise ValueError("Invalid map checkpoint.")
    if "canonical_items" not in snapshot:
        return
    items = snapshot["canonical_items"]
    if not isinstance(items, list) or any(not _valid_item(raw) for raw in items):
        raise ValueError("Invalid canonical item checkpoint.")
    if len({raw["id"] for raw in items}) != len(items):
        raise ValueError("Duplicate canonical item checkpoint entries.")


def _valid_map(raw: Any) -> bool:
    return (
        isinstance(raw, dict)
        and isinstance(raw.get("nodes"), dict)
        and isinstance(raw.get("edges"), list)
        and all(isinstance(edge, dict) for edge in raw["edges"])
    )


def _valid_item(raw: Any) -> bool:
    return (
        isinstance(raw, dict)
        and isinstance(raw.get("id"), str)
        and raw.get("entity_type") == "OBJECT"
        and all(
            isinstance(raw.get(field), str) for field in ("name", "description", "current_scene_id")
        )
    )


async def capture(db: AsyncSession, state: SessionState) -> dict:
    maps = await db.scalars(select(WorldMap).where(WorldMap.session_id == state.session_id))
    items = await db.scalars(
        select(WorldEntity).where(
            WorldEntity.session_id == state.session_id, WorldEntity.entity_type == "OBJECT"
        )
    )
    return {
        "world_map": [
            {
                "id": world.id,
                "nodes": deepcopy(world.nodes),
                "edges": deepcopy(world.edges),
                "current_scene_id": world.current_scene_id,
            }
            for world in maps
        ],
        "canonical_items": [
            {"id": item.id, **{field: deepcopy(getattr(item, field)) for field in _ITEM_FIELDS}}
            for item in items
        ],
    }


async def restore(db: AsyncSession, state: SessionState, snapshot: dict) -> None:
    await _restore_maps(db, state, snapshot)
    saved = snapshot.get("canonical_items")
    if saved is None:
        saved = _legacy_items(snapshot)
    if not isinstance(saved, list):
        raise ValueError("Invalid canonical item checkpoint.")
    rows = list(
        await db.scalars(
            select(WorldEntity).where(
                WorldEntity.session_id == state.session_id, WorldEntity.entity_type == "OBJECT"
            )
        )
    )
    existing = {item.id: item for item in rows}
    for raw in saved:
        _restore_item(db, state.session_id, raw, existing)


def _restore_item(db: AsyncSession, session_id: str, raw: Any, existing: dict) -> None:
    if not isinstance(raw, dict) or not isinstance(raw.get("id"), str):
        raise ValueError("Invalid canonical item checkpoint entry.")
    values = {field: deepcopy(raw[field]) for field in _ITEM_FIELDS if field in raw}
    if values.get("entity_type", "OBJECT") != "OBJECT":
        raise ValueError("An item checkpoint cannot replace a character.")
    row = existing.get(raw["id"])
    if row is None:
        # Partial legacy inline records cannot establish a missing world row.
        if not all(
            field in values for field in ("entity_type", "name", "description", "current_scene_id")
        ):
            return
        row = WorldEntity(id=raw["id"], session_id=session_id, **values)
        db.add(row)
        existing[raw["id"]] = row
        return
    for field, value in values.items():
        setattr(row, field, value)


async def _restore_maps(db: AsyncSession, state: SessionState, snapshot: dict) -> None:
    rows = list(await db.scalars(select(WorldMap).where(WorldMap.session_id == state.session_id)))
    if "world_map" not in snapshot:
        _filter_legacy_maps(rows, state)
        return
    saved = snapshot["world_map"]
    if not isinstance(saved, list):
        raise ValueError("Invalid map checkpoint.")
    # Map row IDs are storage identities, not graph references. Reuse current
    # rows without trusting primary keys from a portable JSON snapshot.
    for index, raw in enumerate(saved):
        if (
            not isinstance(raw, dict)
            or not isinstance(raw.get("nodes"), dict)
            or not isinstance(raw.get("edges"), list)
        ):
            raise ValueError("Invalid map checkpoint entry.")
        world = rows[index] if index < len(rows) else WorldMap(session_id=state.session_id)
        world.nodes, world.edges = deepcopy(raw["nodes"]), deepcopy(raw["edges"])
        world.current_scene_id = state.current_scene_id
        db.add(world)
    for world in rows[len(saved) :]:
        await db.delete(world)


def _filter_legacy_maps(rows: list[WorldMap], state: SessionState) -> None:
    known = set(state.discovered_scenes or []) | {state.current_scene_id}
    for world in rows:
        world.nodes = {key: value for key, value in world.nodes.items() if key in known}
        world.edges = [
            edge
            for edge in world.edges
            if edge.get("from") in world.nodes and edge.get("to") in world.nodes
        ]
        world.current_scene_id = state.current_scene_id


def _legacy_items(snapshot: dict) -> list[dict]:
    avatar, state = snapshot.get("avatar") or {}, snapshot.get("session_state") or {}
    actors = [
        avatar,
        state,
        *[
            value
            for value in (state.get("entity_states") or {}).values()
            if isinstance(value, dict)
        ],
    ]
    result = {}
    for actor in actors:
        entries = [*(actor.get("inventory") or []), *(actor.get("equipment") or {}).values()]
        result.update(
            {
                item["id"]: item
                for item in entries
                if isinstance(item, dict) and isinstance(item.get("id"), str)
            }
        )
    return list(result.values())
