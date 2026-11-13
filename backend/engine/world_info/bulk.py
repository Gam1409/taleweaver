"""Large collections are selected on the server and confirmed against a snapshot."""

import hashlib
import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer

from backend.engine.world_info import limits
from backend.engine.world_info.access import WorldInfoError, reserve_session_write
from backend.engine.world_info.bulk_contracts import BulkApply, BulkRequest
from backend.engine.world_info.bulk_sql import update_entries
from backend.engine.world_info.capacity import ensure_entry_capacity
from backend.engine.world_info.entries import as_draft, proposed_row
from backend.engine.world_info.projection import mark_changed
from backend.engine.world_info.query import entry_query
from backend.engine.world_info.schemas import EntryFilters
from backend.engine.world_info.types import EntryDraft, entry_hash, searchable_text
from backend.engine.world_info.view_records import entry_record
from backend.models.world_info import WorldInfoEntry, WorldInfoRevision, WorldInfoSource


async def _selection(
    db: AsyncSession, user_id: str, session_id: str, payload: BulkRequest
) -> tuple[list[WorldInfoEntry], str, list[Any]]:
    query = await entry_query(db, user_id, session_id, payload.filters)
    entries = list(await db.scalars(query.limit(limits.MAX_SESSION_ENTRIES + 1)))
    if not entries or len(entries) > limits.MAX_SESSION_ENTRIES:
        raise WorldInfoError("Choose a nonempty collection within this session's record limit.")
    sources = (
        list(
            await db.execute(
                select(
                    WorldInfoSource.id,
                    WorldInfoSource.version,
                    WorldInfoSource.current_revision,
                    WorldInfoSource.published_revision,
                )
                .where(
                    WorldInfoSource.user_id == user_id,
                    WorldInfoSource.session_id == session_id,
                    WorldInfoSource.id == entries[0].source_id,
                )
                .order_by(WorldInfoSource.id)
            )
        )
        if payload.action == "publish"
        else []
    )
    revisions = (
        list(
            await db.execute(
                select(
                    WorldInfoRevision.id,
                    WorldInfoRevision.control_version,
                    WorldInfoRevision.cursor,
                    WorldInfoRevision.status,
                )
                .where(
                    WorldInfoRevision.user_id == user_id,
                    WorldInfoRevision.session_id == session_id,
                    WorldInfoRevision.id == payload.filters.source_revision_id,
                )
                .order_by(WorldInfoRevision.id)
            )
        )
        if payload.action == "publish"
        else []
    )
    if any(row.status in {"queued", "processing"} for row in revisions):
        raise WorldInfoError(
            "Finish or stop source processing before publishing this collection.", 409
        )
    values = {
        "owner": user_id,
        "session": session_id,
        "request": payload.model_dump(mode="json", exclude={"selection_hash"}),
        "entries": sorted((entry.id, entry.version, entry.content_hash) for entry in entries),
        "sources": [list(row) for row in sources],
        "revisions": [list(row) for row in revisions],
    }
    digest = hashlib.sha256(
        json.dumps(values, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()
    samples = (
        await db.execute(
            query.add_columns(WorldInfoSource, WorldInfoRevision)
            .options(defer(WorldInfoRevision.content))
            .limit(5)
        )
    ).all()
    return entries, digest, [entry_record(*row) for row in samples]


async def _active_ids(db: AsyncSession, user_id: str, session_id: str) -> set[str]:
    query = await entry_query(db, user_id, session_id, EntryFilters(view="active"))
    return set(await db.scalars(query.with_only_columns(WorldInfoEntry.id)))


async def preview(
    db: AsyncSession, user_id: str, session_id: str, payload: BulkRequest
) -> dict[str, Any]:
    async with db.begin_nested():
        entries, digest, sample = await _selection(db, user_id, session_id, payload)
        active = await _active_ids(db, user_id, session_id)
        source_version = None
        if payload.action == "publish":
            source = await db.get(WorldInfoSource, entries[0].source_id)
            source_version = source.version if source else None
        return {
            "action": payload.action,
            "count": len(entries),
            "facts_count": sum(len(entry.facts) for entry in entries),
            "active_count": sum(entry.id in active for entry in entries),
            "selection_hash": digest,
            "sample": sample,
            "source_version": source_version,
            "source_revision_id": payload.filters.source_revision_id,
        }


def _changed_draft(entry: WorldInfoEntry, payload: BulkRequest) -> EntryDraft:
    values = as_draft(entry).model_dump()
    if payload.action == "set_group":
        values["group_name"] = payload.group_name
    if payload.action == "add_tags":
        values["tags"] = list(dict.fromkeys([*entry.tags, *payload.tags]))
    if payload.action == "remove_tags":
        values["tags"] = [tag for tag in entry.tags if tag not in payload.tags]
    try:
        return EntryDraft.model_validate(values)
    except ValueError:
        raise WorldInfoError(
            "A record would exceed its tag or text budget. Narrow the selection."
        ) from None


async def _edit(
    db: AsyncSession,
    user_id: str,
    session_id: str,
    payload: BulkRequest,
    entries: list[WorldInfoEntry],
) -> int:
    changes: list[dict[str, Any]] = []
    proposed: list[dict[str, Any]] = []
    for entry in entries:
        draft = _changed_draft(entry, payload)
        fingerprint = entry_hash(draft)
        if fingerprint == entry.content_hash:
            continue
        if entry.version >= limits.MAX_COUNTER:
            raise WorldInfoError("A record has reached its revision limit.", 409)
        values = {
            "group_name": draft.group_name,
            "tags": draft.tags,
            "search_text": searchable_text(draft),
            "content_hash": fingerprint,
            "version": entry.version + 1,
            "edited": True,
        }
        changes.append({"old_id": entry.id, "old_version": entry.version, **values})
        proposed.append(proposed_row(entry, **values))
    await ensure_entry_capacity(
        db, user_id, session_id, proposed, replace_ids={row["old_id"] for row in changes}
    )
    active = await _active_ids(db, user_id, session_id)
    await update_entries(db, user_id, session_id, changes)
    if any(row["old_id"] in active for row in changes):
        await mark_changed(db, user_id, session_id)
    return len(changes)


async def apply(
    db: AsyncSession, user_id: str, session_id: str, payload: BulkApply
) -> dict[str, Any]:
    from backend.engine.world_info.publication_batch import publish_selection

    await reserve_session_write(db, user_id, session_id)
    entries, digest, _ = await _selection(db, user_id, session_id, payload)
    if digest != payload.selection_hash:
        raise WorldInfoError("The matching records changed. Preview this selection again.", 409)
    if payload.action == "publish":
        await publish_selection(
            db, user_id, session_id, payload.filters.source_revision_id or "", entries
        )
        changed = len(entries)
    else:
        changed = await _edit(db, user_id, session_id, payload, entries)
    return {"action": payload.action, "matched": len(entries), "changed": changed}
