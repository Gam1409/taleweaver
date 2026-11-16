"""Bounded owner-scoped reads with exact current record counts and sizes."""

from typing import Any, cast

from sqlalchemy import LargeBinary, and_, case, func, select
from sqlalchemy import cast as sql_cast
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer

from backend.engine.memory_rag.settings import read_settings
from backend.engine.world_info import facets, limits
from backend.engine.world_info.query import entry_query, scoped_entries
from backend.engine.world_info.schemas import (
    Character,
    EntryDetail,
    EntryFilters,
    EntryPage,
    EntrySort,
    EntryView,
    IndexState,
    Job,
    RevisionContent,
    RevisionDetail,
    SourceDetail,
    SourceView,
    WorldInfoLimits,
    WorldInfoOverview,
)
from backend.engine.world_info.totals import overview_totals
from backend.engine.world_info.types import EntryKind
from backend.engine.world_info.view_records import (
    ViewNotFoundError,
    entry_record,
    job_record,
    source_record,
)
from backend.models.game_session import GameSession
from backend.models.memory_rag import MemoryIndexState
from backend.models.user import User
from backend.models.world_entity import WorldEntity
from backend.models.world_info import WorldInfoEntry, WorldInfoRevision, WorldInfoSource

entry_facets = facets.entry_facets


async def _owned(db: AsyncSession, user_id: str, session_id: str) -> None:
    found = await db.scalar(
        select(GameSession.id).where(GameSession.id == session_id, GameSession.user_id == user_id)
    )
    if found is None:
        raise ViewNotFoundError("Session not found.")


def _sources(user_id: str, session_id: str) -> Any:
    return (
        select(WorldInfoSource)
        .join(GameSession, GameSession.id == WorldInfoSource.session_id)
        .where(
            GameSession.user_id == user_id,
            WorldInfoSource.user_id == user_id,
            WorldInfoSource.session_id == session_id,
        )
        .execution_options(populate_existing=True)
    )


def _revisions(user_id: str, session_id: str) -> Any:
    return (
        select(WorldInfoRevision)
        .join(WorldInfoSource, WorldInfoSource.id == WorldInfoRevision.source_id)
        .join(GameSession, GameSession.id == WorldInfoSource.session_id)
        .where(
            GameSession.user_id == user_id,
            WorldInfoSource.user_id == user_id,
            WorldInfoSource.session_id == session_id,
            WorldInfoRevision.user_id == user_id,
            WorldInfoRevision.session_id == session_id,
        )
        .options(defer(WorldInfoRevision.content))
        .execution_options(populate_existing=True)
    )


def _entries(user_id: str, session_id: str) -> Any:
    return scoped_entries(user_id, session_id).add_columns(WorldInfoSource, WorldInfoRevision)


async def _sizes(db: AsyncSession, user_id: str, session_id: str) -> dict[str, tuple[int, int]]:
    query = (
        _entries(user_id, session_id)
        .with_only_columns(
            WorldInfoEntry.source_revision_id,
            func.coalesce(func.sum(func.length(WorldInfoEntry.search_text)), 0),
            func.coalesce(
                func.sum(func.length(sql_cast(WorldInfoEntry.search_text, LargeBinary))), 0
            ),
        )
        .group_by(WorldInfoEntry.source_revision_id)
    )
    return {row[0]: (int(row[1]), int(row[2])) for row in await db.execute(query)}


async def index_state(db: AsyncSession, user: User, session_id: str) -> IndexState:
    await _owned(db, user.id, session_id)
    row = await db.scalar(
        select(MemoryIndexState)
        .where(MemoryIndexState.user_id == user.id, MemoryIndexState.session_id == session_id)
        .execution_options(populate_existing=True)
    )
    enabled = read_settings(user).enabled
    return IndexState(
        enabled=enabled,
        paused=bool(row and row.paused),
        status=(row.status if row else "pending") if enabled else "disabled",
        desired_revision=row.desired_revision if row else 0,
        indexed_revision=row.indexed_revision if row else 0,
    )


async def _source_records(db: AsyncSession, sources: list[WorldInfoSource]) -> list[SourceView]:
    if not sources:
        return []
    user_id, session_id = sources[0].user_id, sources[0].session_id
    ids = [source.id for source in sources]
    revisions = list(
        await db.scalars(
            _revisions(user_id, session_id)
            .where(WorldInfoRevision.source_id.in_(ids))
            .order_by(WorldInfoRevision.number.desc())
        )
    )
    sizes = await _sizes(db, user_id, session_id)
    counts = (
        _entries(user_id, session_id)
        .with_only_columns(
            WorldInfoSource.id,
            func.sum(
                case(
                    (
                        and_(
                            WorldInfoEntry.status == "published",
                            WorldInfoSource.published_revision == WorldInfoRevision.number,
                        ),
                        1,
                    ),
                    else_=0,
                )
            ),
            func.sum(case((WorldInfoEntry.status == "draft", 1), else_=0)),
        )
        .where(WorldInfoSource.id.in_(ids))
        .group_by(WorldInfoSource.id)
    )
    totals = {row[0]: (int(row[1]), int(row[2])) for row in await db.execute(counts)}
    return [
        source_record(
            source,
            [row for row in revisions if row.source_id == source.id],
            sizes,
            *totals.get(source.id, (0, 0)),
        )
        for source in sources
    ]


async def overview(db: AsyncSession, user: User, session_id: str) -> WorldInfoOverview:
    await _owned(db, user.id, session_id)
    sources = list(
        await db.scalars(
            _sources(user.id, session_id)
            .order_by(WorldInfoSource.created_at, WorldInfoSource.id)
            .limit(limits.MAX_SOURCES)
        )
    )
    characters = list(
        await db.execute(
            select(WorldEntity.id, WorldEntity.name)
            .where(WorldEntity.session_id == session_id, WorldEntity.entity_type == "NPC")
            .order_by(WorldEntity.name, WorldEntity.id)
        )
    )
    return WorldInfoOverview(
        session_id=session_id,
        sources=await _source_records(db, sources),
        characters=[Character(id=row[0], name=row[1]) for row in characters],
        index=await index_state(db, user, session_id),
        limits=WorldInfoLimits(),
        totals=await overview_totals(db, user.id, session_id),
    )


async def source_view(db: AsyncSession, source: WorldInfoSource) -> SourceView:
    owned = await db.scalar(
        _sources(source.user_id, source.session_id).where(WorldInfoSource.id == source.id)
    )
    if owned is None:
        raise ViewNotFoundError("Source not found.")
    return (await _source_records(db, [owned]))[0]


async def revision_view(db: AsyncSession, revision: WorldInfoRevision) -> Job:
    row = await db.scalar(
        _revisions(revision.user_id, revision.session_id).where(WorldInfoRevision.id == revision.id)
    )
    if row is None:
        raise ViewNotFoundError("Source revision not found.")
    source = await db.scalar(
        _sources(row.user_id, row.session_id).where(WorldInfoSource.id == row.source_id)
    )
    if source is None:
        raise ViewNotFoundError("Source not found.")
    sizes = await _sizes(db, row.user_id, row.session_id)
    return job_record(row, source, sizes.get(row.id, (0, 0)))


async def source_detail(db: AsyncSession, source: WorldInfoSource) -> SourceDetail:
    record = await source_view(db, source)
    rows = list(
        await db.scalars(
            _revisions(source.user_id, source.session_id)
            .where(WorldInfoRevision.source_id == source.id)
            .order_by(WorldInfoRevision.number.desc())
        )
    )
    sizes = await _sizes(db, source.user_id, source.session_id)
    return SourceDetail(
        source=record,
        revisions=[job_record(row, source, sizes.get(row.id, (0, 0))) for row in rows],
    )


async def revision_detail(db: AsyncSession, revision: WorldInfoRevision) -> RevisionDetail:
    job = await revision_view(db, revision)
    source = await db.scalar(
        _sources(revision.user_id, revision.session_id).where(
            WorldInfoSource.id == revision.source_id
        )
    )
    if source is None:
        raise ViewNotFoundError("Source not found.")
    return RevisionDetail(source=await source_view(db, source), revision=job)


async def revision_content(
    db: AsyncSession,
    revision: WorldInfoRevision,
    *,
    offset: int = 0,
    limit: int = limits.MAX_PREVIEW_CHARACTERS,
) -> RevisionContent:
    if (
        type(offset) is not int
        or not 0 <= offset <= limits.MAX_SOURCE_CHARACTERS
        or type(limit) is not int
        or not 1 <= limit <= limits.MAX_PREVIEW_CHARACTERS
    ):
        raise ValueError("Source preview range is invalid.")
    await revision_view(db, revision)
    content = await db.scalar(
        select(func.substr(WorldInfoRevision.content, offset + 1, limit))
        .join(WorldInfoSource, WorldInfoSource.id == WorldInfoRevision.source_id)
        .join(GameSession, GameSession.id == WorldInfoSource.session_id)
        .where(
            WorldInfoRevision.id == revision.id,
            WorldInfoRevision.user_id == revision.user_id,
            WorldInfoRevision.session_id == revision.session_id,
            WorldInfoSource.user_id == revision.user_id,
            WorldInfoSource.session_id == revision.session_id,
            GameSession.user_id == revision.user_id,
        )
    )
    if content is None:
        raise ViewNotFoundError("Source revision not found.")
    keys = (
        "id",
        "filename",
        "format",
        "content_hash",
        "input_bytes",
        "input_characters",
    )
    end = offset + len(content)
    return RevisionContent(
        **{key: getattr(revision, key) for key in keys},
        content=content,
        offset=offset,
        next_offset=end if content and end < revision.input_characters else None,
        total_characters=revision.input_characters,
    )


async def entry_detail(db: AsyncSession, entry: WorldInfoEntry) -> EntryDetail:
    row = (
        await db.execute(
            _entries(entry.user_id, entry.session_id)
            .where(WorldInfoEntry.id == entry.id)
            .options(defer(WorldInfoRevision.content))
        )
    ).first()
    if row is None:
        raise ViewNotFoundError("Entry not found.")
    return cast(EntryDetail, entry_record(*row, detail=True))


async def list_entries(
    db: AsyncSession,
    user_id: str,
    session_id: str,
    *,
    view: EntryView = "review",
    source_revision_id: str | None = None,
    query: str = "",
    group_name: str | None = None,
    tag: str | None = None,
    kind: EntryKind | None = None,
    sort: EntrySort = "newest",
    filters: EntryFilters | None = None,
    offset: int = 0,
    limit: int = 50,
) -> EntryPage:
    if not 0 <= offset <= limits.MAX_COUNTER or not 1 <= limit <= 100:
        raise ValueError("Entry list filters are invalid.")
    selected = filters or EntryFilters(
        view=view,
        source_revision_id=source_revision_id,
        query=query,
        group_name=group_name,
        tag=tag,
        kind=kind,
        sort=sort,
    )
    base = (await entry_query(db, user_id, session_id, selected)).add_columns(
        WorldInfoSource, WorldInfoRevision
    )
    total = int(
        await db.scalar(
            select(func.count()).select_from(
                base.order_by(None).with_only_columns(WorldInfoEntry.id).subquery()
            )
        )
        or 0
    )
    rows = list(
        await db.execute(base.options(defer(WorldInfoRevision.content)).offset(offset).limit(limit))
    )
    return EntryPage(
        entries=[entry_record(*row) for row in rows],
        total=total,
        next_offset=offset + len(rows) if offset + len(rows) < total else None,
    )
