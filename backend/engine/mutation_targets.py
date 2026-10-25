"""Validate mutation targets against canonical entities before applying a turn."""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any

from sqlalchemy import select

from backend.models.world_entity import WorldEntity, WorldScene

logger = logging.getLogger(__name__)


class TargetIndex:
    """Resolve exact IDs and unambiguous exact names; never infer semantic aliases."""

    def __init__(self, records: list[dict]) -> None:
        self.ids: set[str] = set()
        self.folded_ids: dict[str, set[str]] = defaultdict(set)
        self.names: dict[str, set[str]] = defaultdict(set)
        for record in records:
            item_id = str(record.get("id") or "").strip()
            if not item_id:
                continue
            self.ids.add(item_id)
            self.folded_ids[item_id.casefold()].add(item_id)
            name = str(record.get("name") or "").strip().casefold()
            if name:
                self.names[name].add(item_id)

    def resolve(self, raw: Any) -> str | None:
        exact = str(raw or "").strip()
        if exact in self.ids:
            return exact
        key = exact.casefold()
        if key in self.folded_ids:
            candidates = self.folded_ids[key]
            return next(iter(candidates)) if len(candidates) == 1 else None
        candidates = self.names.get(key, set())
        return next(iter(candidates)) if len(candidates) == 1 else None


def _inventory(value: Any) -> list[dict]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


async def _canonical_entities(manager, states):
    result = await manager.db.execute(
        select(WorldEntity).where(WorldEntity.session_id == manager.game_id)
    )
    entities = list(result.scalars().all())
    if entities or not manager.state.template_id:
        return entities
    if "__manifest_snapshot__" in states or "__asset_snapshot__" in states:
        return []
    scene = await manager.db.scalar(
        select(WorldScene.id).where(WorldScene.session_id == manager.game_id).limit(1)
    )
    if scene:
        return []
    # Compatibility for old sessions that still read the template directly.
    result = await manager.db.execute(
        select(WorldEntity).where(
            WorldEntity.template_id == manager.state.template_id,
            WorldEntity.session_id.is_(None),
        )
    )
    return list(result.scalars().all())


def _filter_targets(event, field, index, rejected, attribute=None):
    accepted = []
    for target in getattr(event, field) or []:
        raw = getattr(target, attribute) if attribute else target
        canonical = index.resolve(raw)
        if canonical is None:
            rejected.append(f"{field}: {raw}")
            continue
        if attribute:
            setattr(target, attribute, canonical)
        elif canonical in accepted:
            continue
        accepted.append(target if attribute else canonical)
    if getattr(event, field) is not None:
        setattr(event, field, accepted)


async def validate_mutation_targets(manager, event) -> list[str]:
    """Filter unsupported targets in place so persistence, outcomes and UI agree.

    Memories are unstructured and cannot reliably be attributed to individual
    mutations. If any target is rejected, discard this turn's proposed memories
    and notes while retaining pre-existing history and valid independent changes.
    """
    fields = (
        "updated_entities",
        "moved_entities",
        "deleted_entities",
        "discovered_entity_ids",
        "updated_inventory_items",
        "removed_inventory_item_ids",
    )
    if not any(getattr(event, field) for field in fields):
        return []

    states = manager.state.entity_states
    states = states if isinstance(states, dict) else {}
    entities = await _canonical_entities(manager, states)
    records = [{"id": entity.id, "name": entity.name} for entity in entities]
    possessions = _inventory(manager.avatar.inventory)
    for entity in entities:
        override = states.get(entity.id, {})
        override = override if isinstance(override, dict) else {}
        contained = override.get("inventory", entity.inventory)
        if contained is None:
            metadata = entity.metadata_json if isinstance(entity.metadata_json, dict) else {}
            contained = metadata.get("inventory", [])
        records.extend(_inventory(contained))
    created = [
        item.model_dump()
        for item in (event.new_inventory_items or []) + (event.spawned_items or [])
    ]
    all_targets = TargetIndex(records + possessions + created)
    inventory_targets = TargetIndex(
        possessions + [item.model_dump() for item in event.new_inventory_items or []]
    )
    rejected: list[str] = []
    for field in ("updated_entities", "moved_entities"):
        _filter_targets(event, field, all_targets, rejected, "entity_id")
    for field in ("deleted_entities", "discovered_entity_ids"):
        _filter_targets(event, field, all_targets, rejected)
    _filter_targets(event, "updated_inventory_items", inventory_targets, rejected, "id")
    _filter_targets(event, "removed_inventory_item_ids", inventory_targets, rejected)
    if not rejected:
        return []

    event.new_world_memories = None
    event.remember_notes = None
    event.forget_notes = None
    event.clear_notes = False
    event.narrative_description = (
        "The following proposed changes were NOT executed because their targets do not exist "
        "in the authoritative world or required inventory: " + "; ".join(rejected) + ". "
        "Do not narrate these changes as successful, do not claim an item was destroyed, "
        "consumed or removed for these rejected targets, and do not guess a replacement ID. "
        "Only the remaining structured outcome changes may be described as completed. "
        "Explain the unsuccessful part naturally in the session language without exposing technical IDs."
    )
    logger.warning("[Turn %s] Rejected unknown mutation targets: %s", manager.game_id, rejected)
    return rejected
