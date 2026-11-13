"""Independent session copies and ADS payloads for canonical World Info rows."""

from copy import deepcopy
from typing import Any

import uuid6
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.engine.world_info import limits
from backend.engine.world_info.capacity import validate_entry_capacity
from backend.engine.world_info.portable_schema import (
    PortableEntry,
    PortableRevision,
    PortableRow,
    PortableSource,
    PortableWorldInfo,
    entry_draft,
)
from backend.engine.world_info.types import entry_hash
from backend.models.game_session import GameSession
from backend.models.world_entity import WorldEntity
from backend.models.world_info import WorldInfoEntry, WorldInfoRevision, WorldInfoSource

_MODELS = (
    ("sources", WorldInfoSource, PortableSource),
    ("revisions", WorldInfoRevision, PortableRevision),
    ("entries", WorldInfoEntry, PortableEntry),
)


async def _owned(db: AsyncSession, session_id: str, user_id: str) -> None:
    owned = await db.scalar(
        select(GameSession.id).where(GameSession.id == session_id, GameSession.user_id == user_id)
    )
    if owned is None:
        raise ValueError("World Info session not found.")


def _portable(row: Any, contract: type[PortableRow]) -> dict[str, Any]:
    fields = {key: getattr(row, key) for key in contract.model_fields if hasattr(row, key)}
    try:
        parsed = contract.model_validate(fields)
    except ValidationError:
        raise ValueError("World Info stored row is invalid.") from None
    return parsed.model_dump(mode="json", exclude={"user_id", "session_id"})


def _corpus(payload: Any) -> PortableWorldInfo:
    try:
        return PortableWorldInfo.model_validate({} if payload is None else payload)
    except ValidationError:
        # Importer tracebacks must never include Pydantic's rejected source values.
        raise ValueError("World Info corpus is invalid.") from None


async def export_world_info(db: AsyncSession, session_id: str, user_id: str) -> dict[str, Any]:
    """Export canonical rows only, without credentials or executable job capabilities."""
    # SQLite's legacy SELECT behavior does not start a database read transaction.
    # One short savepoint keeps job cursors/counts and their rows in one snapshot.
    async with db.begin_nested():
        return await _export_snapshot(db, session_id, user_id)


async def _export_snapshot(db: AsyncSession, session_id: str, user_id: str) -> dict[str, Any]:
    await _owned(db, session_id, user_id)
    recipients = await _recipients(db, session_id, user_id)
    payload: dict[str, Any] = {"version": 1}
    for key, model, contract in _MODELS:
        rows = await db.scalars(
            select(model)
            .where(model.session_id == session_id, model.user_id == user_id)
            .order_by(model.created_at, model.id)
            .execution_options(populate_existing=True)
        )
        payload[key] = [_portable(row, contract) for row in rows]
    for entry in payload["entries"]:
        entry["unresolved_known_by"] = sorted(
            set(entry["unresolved_known_by"]) | (set(entry["known_by"]) - recipients)
        )
    return _corpus(payload).model_dump(
        mode="json",
        exclude={
            "sources": {"__all__": {"user_id", "session_id"}},
            "revisions": {"__all__": {"user_id", "session_id"}},
            "entries": {"__all__": {"user_id", "session_id"}},
        },
    )


async def _recipients(db: AsyncSession, session_id: str, user_id: str) -> set[str]:
    return set(
        await db.scalars(
            select(WorldEntity.id)
            .join(GameSession, GameSession.id == WorldEntity.session_id)
            .where(
                WorldEntity.session_id == session_id,
                GameSession.user_id == user_id,
                WorldEntity.entity_type == "NPC",
            )
        )
    )


def _new_ids(payload: PortableWorldInfo) -> dict[str, dict[str, str]]:
    return {
        "sources": {row.id: str(uuid6.uuid7()) for row in payload.sources},
        "revisions": {row.id: str(uuid6.uuid7()) for row in payload.revisions},
        "entries": {row.id: str(uuid6.uuid7()) for row in payload.entries},
        "facts": {fact.id: str(uuid6.uuid7()) for row in payload.entries for fact in row.facts},
    }


def _values(row: PortableRow, new_id: str, session_id: str, user_id: str) -> dict[str, Any]:
    values = row.model_dump(exclude_none=True)
    values.update(id=new_id, session_id=session_id, user_id=user_id)
    return values


def _revision_values(row: PortableRevision, ids: dict, session_id: str, user_id: str) -> dict:
    values = _values(row, ids["revisions"][row.id], session_id, user_id)
    values.update(
        source_id=ids["sources"][row.source_id],
        status="cancelled" if row.status in {"queued", "processing"} else row.status,
        control_version=min(row.control_version + 1, limits.MAX_COUNTER),
        run_token=None,
        lease_token=None,
        lease_until=None,
    )
    return values


def _entry_values(row: PortableEntry, ids: dict, session_id: str, user_id: str) -> dict:
    values = _values(row, ids["entries"][row.id], session_id, user_id)
    values["source_id"] = ids["sources"][row.source_id]
    values["source_revision_id"] = ids["revisions"][row.source_revision_id]
    values["facts"] = [{**fact.model_dump(), "id": ids["facts"][fact.id]} for fact in row.facts]
    values["relations"] = [
        {**relation.model_dump(), "target_id": ids["entries"][relation.target_id]}
        for relation in row.relations
    ]
    remapped = PortableEntry.model_validate(values)
    values["content_hash"] = entry_hash(entry_draft(remapped))
    return values


async def import_world_info(db: AsyncSession, payload: Any, session_id: str, user_id: str) -> None:
    """Validate the complete corpus before adding rows; caller owns commit/rollback."""
    await db.flush()
    await _owned(db, session_id, user_id)
    parsed = _corpus(payload)
    recipients = await _recipients(db, session_id, user_id)
    if any(set(row.known_by) - set(row.unresolved_known_by) - recipients for row in parsed.entries):
        raise ValueError("World Info references a character outside the destination session.")
    existing = await db.scalar(
        select(WorldInfoSource.id).where(WorldInfoSource.session_id == session_id)
    )
    if existing is not None:
        raise ValueError("World Info destination must be empty.")
    ids = _new_ids(parsed)
    sources = [
        WorldInfoSource(**_values(row, ids["sources"][row.id], session_id, user_id))
        for row in parsed.sources
    ]
    revisions = [
        WorldInfoRevision(**_revision_values(row, ids, session_id, user_id))
        for row in parsed.revisions
    ]
    entries = [
        WorldInfoEntry(**_entry_values(row, ids, session_id, user_id)) for row in parsed.entries
    ]
    validate_entry_capacity(entries)
    db.add_all([*sources, *revisions, *entries])
    await db.flush()


async def copy_world_info(
    db: AsyncSession, source_session_id: str, target_session_id: str, user_id: str
) -> None:
    payload = await export_world_info(db, source_session_id, user_id)
    await import_world_info(db, deepcopy(payload), target_session_id, user_id)
