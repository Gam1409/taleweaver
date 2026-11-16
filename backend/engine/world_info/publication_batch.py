"""One accepted revision, validated once and published in bounded SQL batches."""

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.engine.world_info import jobs, limits
from backend.engine.world_info.access import (
    WorldInfoError,
    compare_version,
    owned_revision,
    owned_source,
)
from backend.engine.world_info.bulk_sql import update_entries
from backend.engine.world_info.capacity import ensure_entry_capacity
from backend.engine.world_info.entries import (
    as_draft,
    proposed_row,
    validate_links,
    validate_source,
)
from backend.engine.world_info.projection import mark_changed
from backend.models.world_entity import WorldEntity
from backend.models.world_info import WorldInfoEntry, WorldInfoRevision, WorldInfoSource


async def _archived(
    db: AsyncSession, source: WorldInfoSource, revision: WorldInfoRevision
) -> list[WorldInfoEntry]:
    if source.published_revision is None or source.published_revision == revision.number:
        return []
    return list(
        await db.scalars(
            select(WorldInfoEntry)
            .join(
                WorldInfoRevision,
                WorldInfoRevision.id == WorldInfoEntry.source_revision_id,
            )
            .where(
                WorldInfoEntry.source_id == source.id,
                WorldInfoEntry.user_id == source.user_id,
                WorldInfoEntry.session_id == source.session_id,
                WorldInfoEntry.status == "published",
                WorldInfoRevision.number == source.published_revision,
            )
        )
    )


async def publish_selection(
    db: AsyncSession,
    user_id: str,
    session_id: str,
    revision_id: str,
    selected: Sequence[WorldInfoEntry],
    *,
    expected_source_version: int | None = None,
) -> tuple[int, int, WorldInfoSource]:
    """Caller owns the session write reservation and, optionally, preview digest."""
    revision = await owned_revision(db, user_id, session_id, revision_id, include_content=True)
    source = await owned_source(db, user_id, session_id, revision.source_id)
    if expected_source_version is not None and source.version != expected_source_version:
        raise WorldInfoError("Source changed. Review the publication selection again.", 409)
    if not selected or len(selected) > limits.MAX_SESSION_ENTRIES:
        raise WorldInfoError("Choose a nonempty publication selection.")
    plan = jobs.validate_plan(revision)
    passages = plan.passage_index
    allowed_ids = set(
        await db.scalars(
            select(WorldInfoEntry.id).where(
                WorldInfoEntry.user_id == user_id,
                WorldInfoEntry.session_id == session_id,
            )
        )
    )
    npc_ids = set(
        await db.scalars(
            select(WorldEntity.id).where(
                WorldEntity.session_id == session_id, WorldEntity.entity_type == "NPC"
            )
        )
    )
    for entry in selected:
        if (entry.source_revision_id, entry.user_id, entry.session_id) != (
            revision.id,
            user_id,
            session_id,
        ):
            raise WorldInfoError("Selected records belong to a different revision.", 409)
        draft = as_draft(entry)
        validate_source(entry, draft, revision, plan=plan, passages=passages)
        await validate_links(
            db,
            entry,
            draft,
            entry.audience,
            entry.known_by,
            owned_entry_ids=allowed_ids,
            actual_npc_ids=npc_ids,
        )
    archived = await _archived(db, source, revision)
    statuses = [(entry, "archived") for entry in archived] + [
        (entry, "published") for entry in selected
    ]
    if any(entry.version >= limits.MAX_COUNTER for entry, _ in statuses):
        raise WorldInfoError("A record has reached its revision limit.", 409)
    proposed = [
        proposed_row(entry, status=status, version=entry.version + 1) for entry, status in statuses
    ]
    await ensure_entry_capacity(
        db, user_id, session_id, proposed, replace_ids={entry.id for entry, _ in statuses}
    )
    await compare_version(db, source, source.version, published_revision=revision.number)
    await update_entries(
        db,
        user_id,
        session_id,
        [
            {
                "old_id": entry.id,
                "old_version": entry.version,
                "version": entry.version + 1,
                "status": status,
            }
            for entry, status in statuses
        ],
    )
    await mark_changed(db, user_id, session_id)
    return len(selected), len(archived), source
