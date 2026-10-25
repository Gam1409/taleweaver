"""Persist accepted VN transfers with one owner and consistent world-object visibility."""

from copy import deepcopy
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.engine.rule_engine import GameEvent, InventoryItem
from backend.engine.visual_novel.continuity import PLAYER, SCENE
from backend.models.avatar import Avatar
from backend.models.session_state import SessionState
from backend.models.world_entity import WorldEntity


def _item_id(item: Any) -> str | None:
    if isinstance(item, str):
        return item
    return str(item["id"]) if isinstance(item, dict) and item.get("id") else None


def _destinations(event: GameEvent) -> dict[str, str]:
    destinations = {item.id: PLAYER for item in event.new_inventory_items or [] if item.id}
    destinations.update({item.id: SCENE for item in event.spawned_items or [] if item.id})
    for update in event.updated_entities or []:
        destinations.update(
            {item.id: update.entity_id for item in update.inventory or [] if item.id}
        )
    return destinations


def _holder_inventory(entity: WorldEntity, states: dict) -> list:
    override = states.get(entity.id) or {}
    if "inventory" in override:
        return override["inventory"] or []
    return entity.inventory or (entity.metadata_json or {}).get("inventory") or []


def _remove_previous_owners(
    entities: list[WorldEntity], states: dict, destinations: dict[str, str], removed: set[str]
) -> None:
    for entity in entities:
        previous = _holder_inventory(entity, states)
        kept = [
            item
            for item in previous
            if _item_id(item) not in removed
            and destinations.get(_item_id(item), entity.id) == entity.id
        ]
        if kept != previous:
            states.setdefault(entity.id, {})["inventory"] = deepcopy(kept)


def _materialize_drop(db: AsyncSession, state: SessionState, item: InventoryItem) -> WorldEntity:
    """An existing possession need not already have a scene row; dropping is not generation."""
    canonical = item.model_dump(exclude_none=True)
    columns = WorldEntity.__table__.columns
    fields = {
        key: value
        for key, value in canonical.items()
        if key in InventoryItem.model_fields and key in columns and key != "id"
    }
    fields["description"] = fields.get("description") or ""
    entity = WorldEntity(
        id=item.id,
        session_id=state.session_id,
        entity_type="OBJECT",
        current_scene_id=state.current_scene_id,
        is_in_inventory=False,
        is_hidden=False,
        metadata_json=deepcopy(canonical),
        **fields,
    )
    db.add(entity)
    return entity


async def sync_vn_ownership(
    db: AsyncSession, state: SessionState, avatar: Avatar, event: GameEvent, states: dict[str, Any]
) -> bool:
    """Run after item application and before legacy NPC cleanup; proposals are prevalidated."""
    destinations = _destinations(event)
    removed = set(event.deleted_entities or [])
    if not destinations and not removed:
        return False
    entities = list(
        (await db.execute(select(WorldEntity).where(WorldEntity.session_id == state.session_id)))
        .scalars()
        .all()
    )
    by_id = {entity.id: entity for entity in entities}
    _remove_previous_owners(entities, states, destinations, removed)
    for item in event.spawned_items or []:
        if not item.id:
            continue
        if item.id not in by_id:
            by_id[item.id] = _materialize_drop(db, state, item)
        canonical = item.model_dump(exclude_none=True)
        override = states.setdefault(item.id, {})
        override.update(
            {
                key: value
                for key, value in canonical.items()
                if key in InventoryItem.model_fields and key != "id"
            }
        )
        override["vn_item_data"] = deepcopy(canonical)
    for item_id, owner in destinations.items():
        override = states.setdefault(item_id, {})
        override["is_in_inventory"] = owner != SCENE
        holder = by_id.get(owner)
        scene_id = states.get(owner, {}).get(
            "current_scene_id", getattr(holder, "current_scene_id", None)
        )
        override["current_scene_id"] = scene_id or state.current_scene_id
        if owner == SCENE:
            override["is_hidden"] = False
    outgoing = {item_id for item_id, owner in destinations.items() if owner != PLAYER} | removed
    avatar.equipment = {
        slot: None if _item_id(item) in outgoing else item
        for slot, item in (avatar.equipment or {}).items()
    }
    for item_id in removed:
        states.setdefault(item_id, {}).update(is_in_inventory=False, is_hidden=True)
    return True
