"""Explicit, owner-scoped processing controls; source revisions are durable jobs."""

from typing import Any, cast
from uuid import uuid4

from sqlalchemy import case, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer

from backend.core.content_language import default_language, normalize_language
from backend.engine.world_info import limits
from backend.engine.world_info.parsing import parse_source
from backend.engine.world_info.queue import current_source
from backend.engine.world_info.types import SourceFormat, SourcePlan
from backend.models.game_session import GameSession
from backend.models.user import User
from backend.models.world_info import WorldInfoRevision, WorldInfoSource


class JobNotFoundError(LookupError):
    """The current source revision is unavailable to this session owner."""


class JobConflictError(ValueError):
    """A control request used stale state or would repeat completed processing."""


async def _owned_revision(
    db: AsyncSession,
    user_id: str,
    session_id: str,
    revision_id: str,
    *,
    include_content: bool = False,
) -> WorldInfoRevision:
    query = (
        select(WorldInfoRevision)
        .join(WorldInfoSource, WorldInfoSource.id == WorldInfoRevision.source_id)
        .join(GameSession, GameSession.id == WorldInfoSource.session_id)
        .where(
            WorldInfoRevision.id == revision_id,
            WorldInfoRevision.session_id == session_id,
            WorldInfoRevision.user_id == user_id,
            WorldInfoSource.session_id == session_id,
            WorldInfoSource.user_id == user_id,
            WorldInfoSource.current_revision == WorldInfoRevision.number,
            GameSession.user_id == user_id,
        )
        .execution_options(populate_existing=True)
    )
    if not include_content:
        query = query.options(defer(WorldInfoRevision.content))
    revision = await db.scalar(query)
    if revision is None:
        raise JobNotFoundError("Source revision not found.")
    return revision


def validate_plan(revision: WorldInfoRevision) -> SourcePlan:
    """A changed parser or corrupt cursor must not silently reuse incompatible work."""
    return parse_plan(revision, revision.content)


def parse_plan(revision: WorldInfoRevision, content: str) -> SourcePlan:
    """The raw immutable body is needed only when building a new parsing plan."""
    _validate_versions(revision)
    try:
        plan = parse_source(content, cast(SourceFormat, revision.format))
    except ValueError:
        raise JobConflictError("Saved source integrity check failed.") from None
    return validate_progress(revision, plan)


def _validate_versions(revision: WorldInfoRevision) -> None:
    if (
        revision.parser_version != limits.PARSER_VERSION
        or revision.extraction_version != limits.EXTRACTION_VERSION
    ):
        raise JobConflictError("Source processing version changed. Upload a new revision.")


def validate_progress(revision: WorldInfoRevision, plan: SourcePlan) -> SourcePlan:
    """Recheck current metadata and saved work even when the parsing plan is cached."""
    _validate_versions(revision)
    if (plan.source_hash, plan.bytes, plan.characters, plan.format) != (
        revision.content_hash,
        revision.input_bytes,
        revision.input_characters,
        revision.format,
    ):
        raise JobConflictError("Saved source integrity check failed.")
    if (
        not 0 <= revision.cursor <= len(plan.batches)
        or revision.total_batches not in {0, len(plan.batches)}
        or (revision.cursor and not revision.total_batches)
    ):
        raise JobConflictError("Saved processing progress is invalid.")
    processed = plan.character_offsets[revision.cursor]
    if revision.processed_characters != processed or any(
        not 0 <= value <= limits.MAX_COUNTER
        for value in (revision.entries_count, revision.facts_count, revision.attempts)
    ):
        raise JobConflictError("Saved processing counts are invalid.")
    if revision.cursor and revision.processing_language is None:
        raise JobConflictError("Saved processing language is missing.")
    _validate_language(revision.processing_language)
    return plan


def _validate_language(language: str | None) -> None:
    if language is None:
        return
    try:
        normalized = normalize_language(language)
    except ValueError:
        raise JobConflictError("Saved processing language is invalid.") from None
    if normalized != language:
        raise JobConflictError("Saved processing language is invalid.")


async def _change(
    db: AsyncSession, revision: WorldInfoRevision, expected: int, values: dict
) -> WorldInfoRevision:
    if (
        type(expected) is not int
        or not 1 <= expected < limits.MAX_COUNTER
        or revision.control_version != expected
    ):
        raise JobConflictError("Source processing changed or its control version cannot advance.")
    result = await db.execute(
        update(WorldInfoRevision)
        .where(
            WorldInfoRevision.id == revision.id,
            WorldInfoRevision.control_version == expected,
            WorldInfoRevision.status == revision.status,
            current_source(),
        )
        .values(control_version=expected + 1, **values)
        .execution_options(synchronize_session=False)
    )
    if cast(CursorResult[Any], result).rowcount != 1:
        raise JobConflictError("Source processing changed. Reload and retry.")
    await db.refresh(revision)
    return revision


async def start_processing(
    db: AsyncSession,
    user_id: str,
    session_id: str,
    revision_id: str,
    expected_control_version: int,
) -> WorldInfoRevision:
    """Join the caller transaction; schedule only after its successful commit."""
    revision = await _owned_revision(db, user_id, session_id, revision_id, include_content=True)
    if revision.status not in {"uploaded", "failed", "cancelled"}:
        raise JobConflictError("Only unprocessed or stopped source work can be started.")
    if (
        revision.control_version >= limits.MAX_COUNTER - 1
        or revision.attempts >= limits.MAX_COUNTER
    ):
        raise JobConflictError("Source processing counters are exhausted. Upload a new revision.")
    plan = validate_plan(revision)
    if revision.cursor == len(plan.batches):
        raise JobConflictError("Source processing is complete. Review its saved entries.")
    session = await db.get(GameSession, session_id)
    user = await db.get(User, user_id)
    if session is None or user is None:
        raise JobNotFoundError("Session not found.")
    language = revision.processing_language or default_language(
        session.content_language, user.default_language
    )
    return await _change(
        db,
        revision,
        expected_control_version,
        {
            "status": "queued",
            "total_batches": len(plan.batches),
            "run_token": str(uuid4()),
            "lease_token": None,
            "lease_until": None,
            "last_error_code": None,
            "processing_language": language,
        },
    )


async def cancel_processing(
    db: AsyncSession,
    user_id: str,
    session_id: str,
    revision_id: str,
    expected_control_version: int,
) -> WorldInfoRevision:
    """Revoke publication capability before stopping an optional local await."""
    revision = await _owned_revision(db, user_id, session_id, revision_id)
    if revision.status not in {"queued", "processing"}:
        raise JobConflictError("Source processing is not active.")
    return await _change(
        db,
        revision,
        expected_control_version,
        {
            "status": "cancelled",
            "run_token": None,
            "lease_token": None,
            "lease_until": None,
        },
    )


async def fence_source(db: AsyncSession, user_id: str, session_id: str, source_id: str) -> None:
    """Source replacement/deletion joins the same transaction as token revocation."""
    await db.execute(
        update(WorldInfoRevision)
        .where(
            WorldInfoRevision.source_id == source_id,
            WorldInfoRevision.user_id == user_id,
            WorldInfoRevision.session_id == session_id,
            WorldInfoRevision.status.in_(["queued", "processing"]),
        )
        .values(
            status="cancelled",
            control_version=case(
                (
                    WorldInfoRevision.control_version < limits.MAX_COUNTER,
                    WorldInfoRevision.control_version + 1,
                ),
                else_=limits.MAX_COUNTER,
            ),
            run_token=None,
            lease_token=None,
            lease_until=None,
        )
        .execution_options(synchronize_session=False)
    )


def job_status(revision: WorldInfoRevision) -> dict:
    """Report accepted work; parsing text sizes are distinct from batch completion."""
    fields = (
        "status",
        "cursor",
        "total_batches",
        "processed_characters",
        "facts_count",
        "entries_count",
        "attempts",
        "control_version",
        "last_error_code",
    )
    return {name: getattr(revision, name) for name in fields}
