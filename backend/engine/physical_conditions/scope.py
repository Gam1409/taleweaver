"""Read-only item-state availability; possession authority remains unchanged."""

from dataclasses import dataclass
from typing import Any

from backend.engine.clothing.visuals import value
from backend.engine.npc_journal.presentation import npc_possession_ids
from backend.engine.visual_novel.continuity import (
    PLAYER,
    SCENE,
    Possessions,
    _inventory,
    _override,
    _present,
    possession_snapshot,
)


@dataclass(frozen=True)
class ItemScope:
    additional_items: dict[str, dict]
    item_ids: frozenset[str]
    public_ids: frozenset[str]


def _held_ids(manager: Any, rows: list[Any]) -> set[str]:
    from backend.engine.gameplay.world import AdventureLogic

    inventories = [
        {
            "entity_type": row.entity_type,
            "item_type": getattr(row, "item_type", None),
            "inventory": _inventory(row, _override(manager.state, row.id)),
        }
        for row in rows
    ]
    return AdventureLogic.collect_container_item_ids(inventories) | npc_possession_ids(inventories)


def _visible_ids(manager: Any, rows: list[Any], visible: list[Any] | None) -> set[str]:
    from backend.engine.gameplay.world import _apply_discovery_visibility

    allowed = {str(value(row, "id")) for row in visible} if visible is not None else None
    states = manager.state.entity_states or {}
    normalized = {
        str(key).strip().upper(): row for key, row in states.items() if isinstance(row, dict)
    }
    result = set()
    for row in rows:
        override = _override(manager.state, row.id)
        if row.entity_type != "OBJECT" or not _present(manager, row):
            continue
        if allowed is not None and row.id not in allowed:
            continue
        if override.get("is_in_inventory", getattr(row, "is_in_inventory", False)):
            continue
        discovery = {
            "item_type": getattr(row, "item_type", None),
            "metadata_json": getattr(row, "metadata_json", None),
            "is_hidden": override.get("is_hidden", getattr(row, "is_hidden", False)),
        }
        _apply_discovery_visibility(discovery, states, normalized, row.id, row.id.strip().upper())
        if not discovery["is_hidden"]:
            result.add(row.id)
    return result - _held_ids(manager, rows)


def item_scope(
    manager: Any,
    rows: list[Any],
    *,
    snapshot: Possessions | None = None,
    visible: list[Any] | None = None,
) -> ItemScope:
    """Reuse current scene/ownership gates without making fixed objects transferable."""
    snapshot = snapshot if snapshot is not None else possession_snapshot(manager, rows)
    loose = {
        key
        for key in _visible_ids(manager, rows, visible)
        if snapshot.owners.get(key, SCENE) == SCENE and key in snapshot.catalog
    }
    additional = {key: snapshot.catalog[key] for key in loose if key not in snapshot.items}
    containers = {
        key for key in snapshot.containers if key in loose or snapshot.owners.get(key) == PLAYER
    }
    contents = {key for key, owner in snapshot.owners.items() if owner in containers}
    return ItemScope(
        additional,
        frozenset(snapshot.items) | frozenset(additional),
        frozenset(loose | contents),
    )
