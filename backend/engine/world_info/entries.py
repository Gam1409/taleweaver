"""Review edits retain source evidence and invalidate only accepted knowledge."""

from collections.abc import Mapping
from typing import Any

from pydantic import ValidationError
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.engine.world_info.access import (
    WorldInfoError,
    compare_version,
    is_active,
    owned_entry,
    reserve_session_write,
)
from backend.engine.world_info.capacity import ensure_entry_capacity
from backend.engine.world_info.parsing import parse_source, validate_evidence
from backend.engine.world_info.projection import mark_changed
from backend.engine.world_info.schemas import EntryUpdate
from backend.engine.world_info.types import (
    EntryDraft,
    SourceFormat,
    SourcePassage,
    SourcePlan,
    entry_hash,
    searchable_text,
)
from backend.models.world_entity import WorldEntity
from backend.models.world_info import WorldInfoEntry, WorldInfoRevision


def as_draft(entry: WorldInfoEntry) -> EntryDraft:
    try:
        return EntryDraft.model_validate(
            {key: getattr(entry, key) for key in EntryDraft.model_fields}
        )
    except (ValueError, ValidationError):
        raise WorldInfoError(
            "Saved entry validation failed. Review the source before publishing."
        ) from None


async def validate_links(
    db: AsyncSession,
    entry: WorldInfoEntry,
    draft: EntryDraft,
    audience: str,
    known_by: list[str],
    *,
    owned_entry_ids: set[str] | None = None,
    actual_npc_ids: set[str] | None = None,
) -> None:
    from backend.engine.world_info import limits

    if len(known_by) > limits.MAX_KNOWN_BY or any(not isinstance(value, str) for value in known_by):
        raise WorldInfoError("Choose valid character recipients.")
    target_ids = {relation.target_id for relation in draft.relations}
    targets = (
        owned_entry_ids
        if owned_entry_ids is not None
        else set(
            await db.scalars(
                select(WorldInfoEntry.id).where(
                    WorldInfoEntry.user_id == entry.user_id,
                    WorldInfoEntry.session_id == entry.session_id,
                    WorldInfoEntry.id.in_(target_ids),
                )
            )
        )
    )
    if not target_ids <= targets:
        raise WorldInfoError("Every related entry must belong to this session.")
    npc_ids = (
        actual_npc_ids
        if actual_npc_ids is not None
        else set(
            await db.scalars(
                select(WorldEntity.id).where(
                    WorldEntity.session_id == entry.session_id,
                    WorldEntity.entity_type == "NPC",
                    WorldEntity.id.in_(known_by),
                )
            )
        )
    )
    valid_audience = audience in {"narrator_only", "common_knowledge", "restricted"}
    retained = set(entry.known_by or [])
    valid_recipients = (
        bool(known_by) and set(known_by) <= npc_ids | retained
        if audience == "restricted"
        else not known_by
    )
    if not valid_audience or not valid_recipients or len(set(known_by)) != len(known_by):
        raise WorldInfoError("Choose a valid audience and characters from this session.")


def proposed_row(entry: WorldInfoEntry, **changes: Any) -> dict[str, Any]:
    return {
        column.name: getattr(entry, column.name) for column in WorldInfoEntry.__table__.columns
    } | changes


async def _recipient_edits(
    db: AsyncSession, entry: WorldInfoEntry, payload: EntryUpdate
) -> list[str]:
    unresolved = set(entry.unresolved_known_by or []) & set(payload.known_by)
    requested = set(payload.resolve_known_by)
    current = set(
        await db.scalars(
            select(WorldEntity.id).where(
                WorldEntity.session_id == entry.session_id,
                WorldEntity.entity_type == "NPC",
                WorldEntity.id.in_(requested),
            )
        )
    )
    if requested - current:
        raise WorldInfoError("Reassign knowledge only to a character currently in this session.")
    return sorted(unresolved - requested)


def validate_source(
    entry: WorldInfoEntry,
    draft: EntryDraft,
    revision: WorldInfoRevision,
    *,
    plan: SourcePlan | None = None,
    passages: Mapping[str, SourcePassage] | None = None,
) -> None:
    from typing import cast

    try:
        plan = plan or parse_source(revision.content, cast(SourceFormat, revision.format))
        if (
            plan.source_hash != revision.content_hash
            or not 0 <= entry.batch_index < revision.cursor
        ):
            raise ValueError("Invalid saved source progress.")
        passage_ids = {passage.id for passage in plan.batches[entry.batch_index].passages}
        for evidence in (item for fact in draft.facts for item in fact.evidence):
            if evidence.passage_id not in passage_ids:
                raise ValueError("Invalid saved source batch.")
            validate_evidence(evidence, plan, passages=passages)
    except (ValueError, ValidationError):
        raise WorldInfoError("Entry evidence no longer matches its saved source.") from None


def _edited_draft(entry: WorldInfoEntry, payload: EntryUpdate) -> EntryDraft:
    original = {fact.id: fact for fact in as_draft(entry).facts}
    if len({fact.id for fact in payload.facts}) != len(payload.facts) or any(
        fact.id not in original for fact in payload.facts
    ):
        raise WorldInfoError("Fact edits must retain distinct identities from this entry.")
    facts = [
        original[fact.id].model_copy(
            update={
                "text": fact.text,
                "edited": fact.text != original[fact.id].original_text,
            }
        )
        for fact in payload.facts
    ]
    try:
        return EntryDraft(
            id=entry.id,
            title=payload.title,
            summary=payload.summary,
            kind=payload.kind,
            group_name=entry.group_name if payload.group_name is None else payload.group_name,
            facts=facts,
            tags=payload.tags,
            relations=payload.relations,
        )
    except (ValueError, ValidationError):
        raise WorldInfoError("Entry exceeds its fact, tag, relation or text limits.") from None


async def update_entry(
    db: AsyncSession, user_id: str, session_id: str, entry_id: str, payload: EntryUpdate
) -> WorldInfoEntry:
    await reserve_session_write(db, user_id, session_id)
    entry = await owned_entry(db, user_id, session_id, entry_id)
    if entry.version != payload.version:
        raise WorldInfoError("Entry changed. Reload and retry without discarding your draft.", 409)
    draft = _edited_draft(entry, payload)
    await validate_links(db, entry, draft, payload.audience, payload.known_by)
    unresolved = await _recipient_edits(db, entry, payload)
    active = await is_active(db, entry)
    previous_facts = len(entry.facts)
    values = draft.model_dump(mode="json", exclude={"id"}) | {
        "audience": payload.audience,
        "known_by": payload.known_by,
        "unresolved_known_by": unresolved,
        "search_text": searchable_text(draft),
        "content_hash": entry_hash(draft),
        "edited": True,
    }
    await ensure_entry_capacity(
        db,
        user_id,
        session_id,
        [proposed_row(entry, **values, version=payload.version + 1)],
        replace_ids={entry.id},
    )
    await compare_version(
        db,
        entry,
        payload.version,
        **values,
    )
    await db.execute(
        update(WorldInfoRevision)
        .where(
            WorldInfoRevision.id == entry.source_revision_id,
            WorldInfoRevision.session_id == session_id,
            WorldInfoRevision.user_id == user_id,
        )
        .values(facts_count=WorldInfoRevision.facts_count + len(draft.facts) - previous_facts)
    )
    if active:
        await mark_changed(db, user_id, session_id)
    return entry


async def remove_relations(
    db: AsyncSession, user_id: str, session_id: str, removed_ids: set[str]
) -> bool:
    """Keep remaining records exportable after a target or its source is removed."""
    entries = await db.scalars(
        select(WorldInfoEntry).where(
            WorldInfoEntry.user_id == user_id,
            WorldInfoEntry.session_id == session_id,
            WorldInfoEntry.id.not_in(removed_ids),
        )
    )
    active_changed = False
    for entry in entries:
        draft = as_draft(entry)
        kept = [relation for relation in draft.relations if relation.target_id not in removed_ids]
        if len(kept) == len(draft.relations):
            continue
        active_changed = await is_active(db, entry) or active_changed
        revised = draft.model_copy(update={"relations": kept})
        await compare_version(
            db,
            entry,
            entry.version,
            relations=[r.model_dump() for r in kept],
            content_hash=entry_hash(revised),
            edited=True,
        )
    return active_changed


async def remove_entry(
    db: AsyncSession, user_id: str, session_id: str, entry_id: str, expected_version: int
) -> None:
    await reserve_session_write(db, user_id, session_id)
    entry = await owned_entry(db, user_id, session_id, entry_id)
    active = await is_active(db, entry)
    await compare_version(db, entry, expected_version)
    linked_active = await remove_relations(db, user_id, session_id, {entry.id})
    await db.execute(
        update(WorldInfoRevision)
        .where(
            WorldInfoRevision.id == entry.source_revision_id,
            WorldInfoRevision.user_id == user_id,
            WorldInfoRevision.session_id == session_id,
        )
        .values(
            facts_count=WorldInfoRevision.facts_count - len(entry.facts),
            entries_count=WorldInfoRevision.entries_count - 1,
        )
    )
    await db.execute(delete(WorldInfoEntry).where(WorldInfoEntry.id == entry.id))
    if active or linked_active:
        await mark_changed(db, user_id, session_id)


async def unpublish(
    db: AsyncSession, user_id: str, session_id: str, entry_id: str, expected_version: int
) -> WorldInfoEntry:
    await reserve_session_write(db, user_id, session_id)
    entry = await owned_entry(db, user_id, session_id, entry_id)
    active = await is_active(db, entry)
    await ensure_entry_capacity(
        db,
        user_id,
        session_id,
        [proposed_row(entry, status="draft", version=expected_version + 1)],
        replace_ids={entry.id},
    )
    await compare_version(db, entry, expected_version, status="draft")
    if active:
        await mark_changed(db, user_id, session_id)
    return entry
