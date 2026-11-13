"""Immutable uploads and owner-controlled source replacement."""

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.engine.world_info import jobs, limits
from backend.engine.world_info.access import (
    WorldInfoError,
    compare_version,
    owned_source,
    reserve_session_write,
)
from backend.engine.world_info.parsing import parse_source
from backend.engine.world_info.types import SourceFormat, SourcePlan, validate_text
from backend.models.world_info import WorldInfoEntry, WorldInfoRevision, WorldInfoSource


async def _capacity(db: AsyncSession, user_id: str, session_id: str, size: int) -> int:
    count = await db.scalar(
        select(func.count(WorldInfoSource.id)).where(
            WorldInfoSource.user_id == user_id, WorldInfoSource.session_id == session_id
        )
    )
    stored = await db.scalar(
        select(func.coalesce(func.sum(WorldInfoRevision.input_bytes), 0)).where(
            WorldInfoRevision.user_id == user_id, WorldInfoRevision.session_id == session_id
        )
    )
    if int(stored or 0) + size > limits.MAX_SESSION_SOURCE_BYTES:
        raise WorldInfoError(
            "Session source storage is full. Remove a source before uploading.", 413
        )
    return int(count or 0)


def _revision(
    source: WorldInfoSource, filename: str, content: str, plan: SourcePlan
) -> WorldInfoRevision:
    return WorldInfoRevision(
        source_id=source.id,
        user_id=source.user_id,
        session_id=source.session_id,
        number=source.current_revision,
        filename=filename,
        format=plan.format,
        content=content,
        content_hash=plan.source_hash,
        input_bytes=plan.bytes,
        input_characters=plan.characters,
        parser_version=limits.PARSER_VERSION,
        extraction_version=limits.EXTRACTION_VERSION,
        total_batches=len(plan.batches),
    )


async def upload(
    db: AsyncSession,
    user_id: str,
    session_id: str,
    *,
    filename: str,
    content: str,
    format: SourceFormat,
    title: str | None = None,
) -> tuple[WorldInfoSource, WorldInfoRevision, bool]:
    await reserve_session_write(db, user_id, session_id)
    plan = parse_source(content, format)
    clean_title = validate_text(title if title is not None else filename).strip()
    if not clean_title or len(clean_title) > 200:
        raise WorldInfoError("Source title must contain 1 to 200 characters.")
    duplicate = await db.scalar(
        select(WorldInfoRevision)
        .join(WorldInfoSource, WorldInfoSource.id == WorldInfoRevision.source_id)
        .where(
            WorldInfoSource.user_id == user_id,
            WorldInfoSource.session_id == session_id,
            WorldInfoSource.current_revision == WorldInfoRevision.number,
            WorldInfoRevision.content_hash == plan.source_hash,
            WorldInfoRevision.format == format,
        )
    )
    if duplicate is not None:
        source = await owned_source(db, user_id, session_id, duplicate.source_id)
        return source, duplicate, True
    if await _capacity(db, user_id, session_id, plan.bytes) >= limits.MAX_SOURCES:
        raise WorldInfoError("Session source limit reached. Remove a source before uploading.", 413)
    source = WorldInfoSource(
        user_id=user_id, session_id=session_id, title=clean_title, filename=filename, format=format
    )
    db.add(source)
    await db.flush()
    revision = _revision(source, filename, content, plan)
    db.add(revision)
    await db.flush()
    return source, revision, False


async def replace(
    db: AsyncSession,
    user_id: str,
    session_id: str,
    source_id: str,
    expected_version: int,
    *,
    filename: str,
    content: str,
    format: SourceFormat,
) -> tuple[WorldInfoSource, WorldInfoRevision, bool]:
    await reserve_session_write(db, user_id, session_id)
    source = await owned_source(db, user_id, session_id, source_id)
    if source.version != expected_version:
        raise WorldInfoError("Source changed. Reload and retry.", 409)
    plan = parse_source(content, format)
    previous = await db.scalar(
        select(WorldInfoRevision).where(
            WorldInfoRevision.source_id == source.id,
            WorldInfoRevision.number == source.current_revision,
        )
    )
    if previous is not None and (previous.content_hash, previous.format) == (
        plan.source_hash,
        format,
    ):
        return source, previous, True
    if source.current_revision >= limits.MAX_SOURCE_REVISIONS:
        raise WorldInfoError("Source revision limit reached. Upload a separate source.", 413)
    await _capacity(db, user_id, session_id, plan.bytes)
    await compare_version(
        db,
        source,
        expected_version,
        current_revision=source.current_revision + 1,
        filename=filename,
        format=format,
    )
    await jobs.fence_source(db, user_id, session_id, source_id)
    revision = _revision(source, filename, content, plan)
    db.add(revision)
    await db.flush()
    return source, revision, False


async def remove(
    db: AsyncSession, user_id: str, session_id: str, source_id: str, expected_version: int
) -> None:
    from backend.engine.world_info.entries import remove_relations
    from backend.engine.world_info.projection import mark_changed

    await reserve_session_write(db, user_id, session_id)
    source = await owned_source(db, user_id, session_id, source_id)
    await compare_version(db, source, expected_version)
    await jobs.fence_source(db, user_id, session_id, source_id)
    entries = list(
        await db.scalars(select(WorldInfoEntry).where(WorldInfoEntry.source_id == source.id))
    )
    affected = await remove_relations(db, user_id, session_id, {entry.id for entry in entries})
    if source.published_revision is not None or affected:
        await mark_changed(db, user_id, session_id)
    await db.execute(delete(WorldInfoEntry).where(WorldInfoEntry.source_id == source.id))
    await db.execute(delete(WorldInfoRevision).where(WorldInfoRevision.source_id == source.id))
    await db.delete(source)
    await db.flush()
