"""Owner and revision boundaries for session knowledge operations."""

from typing import Any, cast

from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer

from backend.engine.world_info import limits
from backend.models.game_session import GameSession
from backend.models.world_info import WorldInfoEntry, WorldInfoRevision, WorldInfoSource


class WorldInfoError(ValueError):
    """A safe, host-authored error suitable for the owner-facing API."""

    def __init__(self, detail: str, status: int = 422) -> None:
        super().__init__(detail)
        self.status = status


async def reserve_session_write(db: AsyncSession, user_id: str, session_id: str) -> None:
    """Serialize short quota checks without changing gameplay data or timestamps.

    SQLite's legacy SELECT handling can leave two uploads reading the same free
    capacity before either starts a write transaction. This owner-scoped no-op
    write acquires the writer first; callers commit or roll back their operation.
    SQLite's database writer lock also serializes independent processes. The local
    gameplay lease separately prevents overlap with streamed turns.
    """
    with db.no_autoflush:
        result = await db.execute(
            update(GameSession)
            .where(GameSession.id == session_id, GameSession.user_id == user_id)
            .values(id=GameSession.id, updated_at=GameSession.updated_at)
            .execution_options(synchronize_session=False)
        )
    if cast(CursorResult[Any], result).rowcount != 1:
        raise WorldInfoError("Session not found.", 404)


async def owned_session(db: AsyncSession, user_id: str, session_id: str) -> GameSession:
    session = await db.scalar(
        select(GameSession).where(GameSession.id == session_id, GameSession.user_id == user_id)
    )
    if session is None:
        raise WorldInfoError("Session not found.", 404)
    return session


async def owned_source(
    db: AsyncSession, user_id: str, session_id: str, source_id: str
) -> WorldInfoSource:
    source = await db.scalar(
        select(WorldInfoSource)
        .join(GameSession, GameSession.id == WorldInfoSource.session_id)
        .where(
            WorldInfoSource.id == source_id,
            WorldInfoSource.user_id == user_id,
            WorldInfoSource.session_id == session_id,
            GameSession.user_id == user_id,
        )
        .execution_options(populate_existing=True)
    )
    if source is None:
        raise WorldInfoError("Source not found.", 404)
    return source


async def owned_revision(
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
            WorldInfoRevision.user_id == user_id,
            WorldInfoRevision.session_id == session_id,
            WorldInfoSource.user_id == user_id,
            WorldInfoSource.session_id == session_id,
            GameSession.user_id == user_id,
        )
        .execution_options(populate_existing=True)
    )
    if not include_content:
        query = query.options(defer(WorldInfoRevision.content))
    revision = await db.scalar(query)
    if revision is None:
        raise WorldInfoError("Source revision not found.", 404)
    return revision


async def owned_entry(
    db: AsyncSession, user_id: str, session_id: str, entry_id: str
) -> WorldInfoEntry:
    entry = await db.scalar(
        select(WorldInfoEntry)
        .join(WorldInfoRevision, WorldInfoRevision.id == WorldInfoEntry.source_revision_id)
        .join(WorldInfoSource, WorldInfoSource.id == WorldInfoEntry.source_id)
        .join(GameSession, GameSession.id == WorldInfoEntry.session_id)
        .where(
            WorldInfoEntry.id == entry_id,
            WorldInfoEntry.user_id == user_id,
            WorldInfoEntry.session_id == session_id,
            WorldInfoRevision.source_id == WorldInfoEntry.source_id,
            WorldInfoRevision.user_id == user_id,
            WorldInfoRevision.session_id == session_id,
            WorldInfoSource.user_id == user_id,
            WorldInfoSource.session_id == session_id,
            GameSession.user_id == user_id,
        )
        .execution_options(populate_existing=True)
    )
    if entry is None:
        raise WorldInfoError("Entry not found.", 404)
    return entry


async def compare_version(
    db: AsyncSession,
    row: WorldInfoSource | WorldInfoEntry,
    expected: int,
    **values: Any,
) -> None:
    if (
        type(expected) is not int
        or not 1 <= expected < limits.MAX_COUNTER
        or row.version != expected
    ):
        raise WorldInfoError(
            "World Info changed or its version cannot advance. Reload and retry.", 409
        )
    model = type(row)
    result = await db.execute(
        update(model)
        .where(
            model.id == row.id,
            model.user_id == row.user_id,
            model.session_id == row.session_id,
            model.version == expected,
        )
        .values(version=expected + 1, **values)
        .execution_options(synchronize_session=False)
    )
    if cast(CursorResult[Any], result).rowcount != 1:
        raise WorldInfoError("World Info changed. Reload and retry; your draft was not saved.", 409)
    await db.refresh(row)


async def is_active(db: AsyncSession, entry: WorldInfoEntry) -> bool:
    active = await db.scalar(
        select(WorldInfoSource.id)
        .join(WorldInfoRevision, WorldInfoRevision.source_id == WorldInfoSource.id)
        .where(
            WorldInfoSource.id == entry.source_id,
            WorldInfoSource.user_id == entry.user_id,
            WorldInfoSource.session_id == entry.session_id,
            WorldInfoSource.published_revision == WorldInfoRevision.number,
            WorldInfoRevision.id == entry.source_revision_id,
        )
    )
    return entry.status == "published" and active is not None
