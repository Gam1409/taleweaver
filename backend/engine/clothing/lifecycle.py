"""Checkpoint cleanup for explicitly marked runtime garments, never ID-prefix guesses."""

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.world_entity import WorldEntity

CHECKPOINT_KEY = "clothing_item_ids"


def _item_ids(items: Any) -> set[str]:
    values = items.values() if isinstance(items, dict) else items
    if not isinstance(values, (list, tuple)) and not isinstance(items, dict):
        return set()
    return {
        identifier
        for item in values
        if (identifier := item.get("id") if isinstance(item, dict) else item)
        and isinstance(identifier, str)
    }


def _stored_item_ids(avatar: dict, state: dict) -> set[str]:
    identifiers = _item_ids(avatar.get("inventory")) | _item_ids(avatar.get("equipment"))
    identifiers.update(_item_ids(state.get("inventory")))
    overrides = state.get("entity_states") or {}
    if not isinstance(overrides, dict):
        return identifiers
    for override in overrides.values():
        if not isinstance(override, dict):
            continue
        identifiers.update(_item_ids(override.get("inventory")))
        identifiers.update(_item_ids(override.get("equipment")))
    return identifiers


async def capture_item_ids(db: AsyncSession, session_id: str, snapshot: dict) -> list[str]:
    """An owned garment may not have a world row until it is dropped later."""
    known = _stored_item_ids(snapshot.get("avatar") or {}, snapshot.get("session_state") or {})
    rows = await db.execute(
        select(WorldEntity.id, WorldEntity.inventory).where(WorldEntity.session_id == session_id)
    )
    for identifier, inventory in rows:
        known.add(identifier)
        known.update(_item_ids(inventory))
    return sorted(known)


async def rewind_created_garments(
    db: AsyncSession, session_id: str, snapshot: dict, removed_message_ids: list[str]
) -> None:
    """Delete only later creations with matching runtime provenance.

    Old checkpoints lack the explicit ID snapshot; then a removed source message
    is required. Unknown provenance and imported/base rows are always retained.
    """
    raw_known = snapshot.get(CHECKPOINT_KEY)
    explicit = isinstance(raw_known, list) and all(isinstance(item, str) for item in raw_known)
    known = set(raw_known) if explicit else set()
    known.update(
        _stored_item_ids(snapshot.get("avatar") or {}, snapshot.get("session_state") or {})
    )
    removed = set(removed_message_ids)
    rows = await db.scalars(
        select(WorldEntity).where(
            WorldEntity.session_id == session_id,
            WorldEntity.entity_type == "OBJECT",
        )
    )
    for row in rows:
        metadata = row.metadata_json if isinstance(row.metadata_json, dict) else {}
        origin = metadata.get("clothing_origin")
        if not _runtime_origin(origin, session_id) or row.id in known:
            continue
        if explicit or origin.get("source_message_id") in removed:
            await db.delete(row)


def _runtime_origin(origin: Any, session_id: str) -> bool:
    return (
        isinstance(origin, dict)
        and origin.get("kind") == "runtime"
        and origin.get("session_id") == session_id
    )
