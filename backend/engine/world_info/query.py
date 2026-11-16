"""One owner-scoped SQL selector shared by pages, facets and explicit bulk work."""

from sqlalchemy import Select, and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.engine.world_info.schemas import EntryFilters
from backend.engine.world_info.view_records import ViewNotFoundError
from backend.models.game_session import GameSession
from backend.models.world_info import WorldInfoEntry, WorldInfoRevision, WorldInfoSource
from backend.utils.sqlite_text import casefold


def scoped_entries(user_id: str, session_id: str) -> Select[tuple[WorldInfoEntry]]:
    """Select entities only; joined immutable source text is never materialized."""
    return (
        select(WorldInfoEntry)
        .join(WorldInfoSource, WorldInfoSource.id == WorldInfoEntry.source_id)
        .join(
            WorldInfoRevision,
            and_(
                WorldInfoRevision.id == WorldInfoEntry.source_revision_id,
                WorldInfoRevision.source_id == WorldInfoSource.id,
            ),
        )
        .join(GameSession, GameSession.id == WorldInfoEntry.session_id)
        .where(
            GameSession.user_id == user_id,
            WorldInfoEntry.user_id == user_id,
            WorldInfoEntry.session_id == session_id,
            WorldInfoSource.user_id == user_id,
            WorldInfoSource.session_id == session_id,
            WorldInfoRevision.user_id == user_id,
            WorldInfoRevision.session_id == session_id,
        )
        .execution_options(populate_existing=True)
    )


async def _authorize(
    db: AsyncSession, user_id: str, session_id: str, filters: EntryFilters
) -> None:
    owned = await db.scalar(
        select(GameSession.id).where(GameSession.id == session_id, GameSession.user_id == user_id)
    )
    if owned is None:
        raise ViewNotFoundError("Session not found.")
    if filters.source_revision_id is None:
        return
    revision = await db.scalar(
        select(WorldInfoRevision.id)
        .join(WorldInfoSource, WorldInfoSource.id == WorldInfoRevision.source_id)
        .where(
            WorldInfoRevision.id == filters.source_revision_id,
            WorldInfoRevision.user_id == user_id,
            WorldInfoRevision.session_id == session_id,
            WorldInfoSource.user_id == user_id,
            WorldInfoSource.session_id == session_id,
        )
    )
    if revision is None:
        raise ViewNotFoundError("Source revision not found.")


def _sort(
    query: Select[tuple[WorldInfoEntry]], filters: EntryFilters
) -> Select[tuple[WorldInfoEntry]]:
    title = func.tw_casefold(WorldInfoEntry.title)
    orders = {
        "newest": (WorldInfoEntry.updated_at.desc(), WorldInfoEntry.id),
        "oldest": (WorldInfoEntry.updated_at.asc(), WorldInfoEntry.id),
        "title_asc": (title.asc(), WorldInfoEntry.id),
        "title_desc": (title.desc(), WorldInfoEntry.id),
        "source": (
            func.tw_casefold(WorldInfoSource.title),
            WorldInfoSource.id,
            WorldInfoRevision.number,
            WorldInfoEntry.batch_index,
            WorldInfoEntry.ordinal,
            WorldInfoEntry.id,
        ),
    }
    return query.order_by(*orders[filters.sort])


async def entry_query(
    db: AsyncSession, user_id: str, session_id: str, filters: EntryFilters
) -> Select[tuple[WorldInfoEntry]]:
    """Apply validated filters without pagination; callers bound materialization."""
    await _authorize(db, user_id, session_id, filters)
    query = scoped_entries(user_id, session_id)
    if filters.source_revision_id is not None:
        query = query.where(WorldInfoRevision.id == filters.source_revision_id)
    if filters.view == "review":
        query = query.where(WorldInfoEntry.status == "draft")
        if filters.source_revision_id is None:
            query = query.where(WorldInfoSource.current_revision == WorldInfoRevision.number)
    if filters.view == "active":
        query = query.where(
            WorldInfoEntry.status == "published",
            WorldInfoSource.published_revision == WorldInfoRevision.number,
        )
    for term in dict.fromkeys(casefold(filters.query).split()):
        query = query.where(
            func.tw_casefold(WorldInfoEntry.search_text).contains(term, autoescape=True)
        )
    if filters.group_name is not None:
        query = query.where(WorldInfoEntry.group_name == filters.group_name)
    if filters.kind is not None:
        query = query.where(WorldInfoEntry.kind == filters.kind)
    if filters.tag is not None:
        tags = func.json_each(WorldInfoEntry.tags).table_valued("value")
        tagged = (
            select(1)
            .select_from(tags)
            .where(tags.c.value == filters.tag)
            .correlate(WorldInfoEntry)
            .exists()
        )
        query = query.where(tagged)
    return _sort(query, filters)
