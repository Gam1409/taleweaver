"""Publish validated item changes through the canonical inventory and scene owners."""

from copy import deepcopy
from typing import Any

from backend.engine.clothing.context import actor_records
from backend.engine.clothing.runtime import _store_actor
from backend.engine.clothing.visuals import session_objects
from backend.engine.scene_staging.props import clear_item
from backend.engine.visual_novel.continuity import (
    SCENE,
    CanonicalInventoryItem,
    Possessions,
    possession_snapshot,
)
from backend.engine.visual_novel.ownership import materialize_scene_possession


def store_changes(manager: Any, changed: dict, accepted: list[dict], catalog: dict) -> None:
    """Retain unrelated actor fields and distinguish carried from loose scene objects."""
    states = deepcopy(manager.state.entity_states or {})
    affected = {entry[key] for entry in accepted for key in ("source_owner", "destination_owner")}
    for identifier in affected - {SCENE}:
        _store_actor(manager, states, changed[identifier])
    for entry in accepted:
        identifier = entry["item"]["id"]
        if identifier not in catalog:
            continue
        loose = entry["destination_owner"] == SCENE
        states[identifier] = {
            **states.get(identifier, {}),
            "is_in_inventory": not loose,
            "current_scene_id": manager.state.current_scene_id,
            "vn_item_data": deepcopy(entry["item"]),
            **({"is_hidden": False} if loose else {}),
        }
    manager.state.entity_states = states


def _check_current(
    before: dict, current: dict, snapshot: Possessions, fresh: Possessions, entry: dict
) -> None:
    identifier = entry["item"]["id"]
    if snapshot.owners.get(identifier) != fresh.owners.get(identifier) or snapshot.items.get(
        identifier
    ) != fresh.items.get(identifier):
        raise ValueError("Item custody or current attributes changed after command preparation.")
    affected = {entry["source_owner"], entry["destination_owner"]} - {SCENE}
    for actor in affected:
        if actor not in current or before.get(actor) != current[actor]:
            raise ValueError("Actor inventory or appearance changed after command preparation.")


async def publish_command(
    manager: Any, before: dict, snapshot: Possessions, changed: dict, entry: dict
) -> None:
    """Recheck a host-built transfer before writing; the enclosing turn owns the transaction."""
    rows = await session_objects(manager.db, manager.game_id)
    fresh = possession_snapshot(manager, rows)
    _check_current(before, actor_records(manager, rows), snapshot, fresh, entry)
    identifier = entry["item"]["id"]
    row = next((row for row in rows if row.id == identifier and row.entity_type == "OBJECT"), None)
    loose = entry["destination_owner"] == SCENE
    if row is None and loose:
        item = CanonicalInventoryItem.model_validate(deepcopy(entry["item"]))
        row = materialize_scene_possession(manager.db, manager.state, item)
    store_changes(
        manager, changed, [entry], {**fresh.catalog, **({identifier: entry["item"]} if row else {})}
    )
    if row is not None:
        row.spatial_position = entry.get("spatial_position")
        row.current_scene_id = manager.state.current_scene_id
        row.is_in_inventory = not loose
        if loose:
            row.is_hidden = False
        states = deepcopy(manager.state.entity_states)
        states[identifier]["spatial_position"] = row.spatial_position
        manager.state.entity_states = states
    clear_item(manager.state, identifier)
