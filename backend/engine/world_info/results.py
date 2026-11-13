"""Commit a validated draft batch once, independently from its model request."""

from collections.abc import Sequence
from typing import Any, cast
from uuid import UUID

from sqlalchemy import or_, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer

from backend.core import database
from backend.engine.memory_rag.persistence import retry_transaction
from backend.engine.world_info import limits, plan_cache, queue
from backend.engine.world_info.capacity import ensure_entry_capacity
from backend.engine.world_info.parsing import validate_evidence
from backend.engine.world_info.types import (
    EntryDraft,
    SourcePlan,
    entry_content_hash,
    entry_search_text,
)
from backend.models.world_info import WorldInfoEntry, WorldInfoRevision, WorldInfoSource


def _validate_entries(entries: Sequence[EntryDraft], plan: SourcePlan, batch_index: int) -> None:
    facts = [fact for entry in entries for fact in entry.facts]
    if (
        len(entries) > limits.MAX_BATCH_ENTRIES
        or len(facts) > limits.MAX_BATCH_FACTS
        or len({entry.id for entry in entries}) != len(entries)
        or len({fact.id for fact in facts}) != len(facts)
    ):
        raise ValueError("Batch exceeds its distinct entry or fact budget.")
    passages = {passage.id: passage for passage in plan.batches[batch_index].passages}
    for entry in entries:
        UUID(entry.id)
    for evidence in (evidence for fact in facts for evidence in fact.evidence):
        if evidence.passage_id not in passages:
            raise ValueError("Evidence belongs to another source batch.")
        validate_evidence(evidence, plan, passages=passages)


def _new_entry(claim: queue.Claim, entry: EntryDraft, ordinal: int) -> WorldInfoEntry:
    return WorldInfoEntry(
        id=entry.id,
        user_id=claim.user_id,
        session_id=claim.session_id,
        source_id=claim.source_id,
        source_revision_id=claim.revision_id,
        batch_index=claim.cursor,
        ordinal=ordinal,
        title=entry.title,
        summary=entry.summary,
        facts=[fact.model_dump(mode="json") for fact in entry.facts],
        tags=list(entry.tags),
        group_name=entry.group_name,
        relations=[relation.model_dump(mode="json") for relation in entry.relations],
        kind=entry.kind,
        audience="narrator_only",
        known_by=[],
        status="draft",
        search_text=entry_search_text(entry),
        content_hash=entry_content_hash(entry),
    )


async def _check_capacity(
    db: AsyncSession, claim: queue.Claim, entries: Sequence[EntryDraft]
) -> None:
    proposed = [_new_entry(claim, entry, ordinal) for ordinal, entry in enumerate(entries)]
    await ensure_entry_capacity(db, claim.user_id, claim.session_id, proposed)


async def _check_relations(
    db: AsyncSession, claim: queue.Claim, entries: Sequence[EntryDraft]
) -> None:
    local = {entry.id for entry in entries}
    targets = {relation.target_id for entry in entries for relation in entry.relations} - local
    if not targets:
        return
    available = set(
        await db.scalars(
            select(WorldInfoEntry.id)
            .join(WorldInfoRevision, WorldInfoRevision.id == WorldInfoEntry.source_revision_id)
            .join(WorldInfoSource, WorldInfoSource.id == WorldInfoEntry.source_id)
            .where(
                WorldInfoEntry.id.in_(targets),
                WorldInfoEntry.session_id == claim.session_id,
                WorldInfoEntry.user_id == claim.user_id,
                WorldInfoSource.session_id == claim.session_id,
                WorldInfoSource.user_id == claim.user_id,
                WorldInfoEntry.status.in_(["draft", "published"]),
                or_(
                    WorldInfoSource.current_revision == WorldInfoRevision.number,
                    WorldInfoSource.published_revision == WorldInfoRevision.number,
                ),
            )
        )
    )
    if targets != available:
        raise ValueError("Relation target is no longer available in this session.")


@retry_transaction
async def save_batch(claim: queue.Claim, entries: Sequence[EntryDraft]) -> bool:
    """A committed cursor and deterministic IDs survive an uncertain commit outcome."""
    async with database.AsyncSessionLocal() as db:
        locked = await db.execute(
            update(WorldInfoRevision)
            .where(*queue.fence(claim))
            .values(last_error_code=None)
            .execution_options(synchronize_session=False)
        )
        if cast(CursorResult[Any], locked).rowcount != 1:
            return False
        revision = await db.scalar(
            select(WorldInfoRevision)
            .where(WorldInfoRevision.id == claim.revision_id)
            .options(defer(WorldInfoRevision.content))
        )
        if revision is None:
            return False
        plan = await plan_cache.load(db, revision)
        _validate_entries(entries, plan, claim.cursor)
        await _check_capacity(db, claim, entries)
        await _check_relations(db, claim, entries)
        db.add_all(_new_entry(claim, entry, ordinal) for ordinal, entry in enumerate(entries))
        completed = claim.cursor + 1
        characters = sum(len(passage.text) for passage in plan.batches[claim.cursor].passages)
        await db.execute(
            update(WorldInfoRevision)
            .where(*queue.fence(claim))
            .values(
                cursor=completed,
                total_batches=len(plan.batches),
                processed_characters=WorldInfoRevision.processed_characters + characters,
                entries_count=WorldInfoRevision.entries_count + len(entries),
                facts_count=WorldInfoRevision.facts_count
                + sum(len(entry.facts) for entry in entries),
                status="review" if completed == len(plan.batches) else "queued",
                lease_token=None,
                lease_until=None,
                run_token=None if completed == len(plan.batches) else claim.run_token,
            )
        )
        await db.commit()
        return True
