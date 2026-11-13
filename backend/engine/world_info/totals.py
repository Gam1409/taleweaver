"""Constant-size aggregate totals for a session knowledge catalog."""

from sqlalchemy import LargeBinary, and_, case, func, select
from sqlalchemy import cast as sql_cast
from sqlalchemy.ext.asyncio import AsyncSession

from backend.engine.world_info.query import scoped_entries
from backend.engine.world_info.schemas import OverviewTotals
from backend.models.game_session import GameSession
from backend.models.world_info import WorldInfoEntry, WorldInfoRevision, WorldInfoSource


async def overview_totals(db: AsyncSession, user_id: str, session_id: str) -> OverviewTotals:
    """The caller already authorizes the session; every aggregate retains owner filters."""
    entries = scoped_entries(user_id, session_id).with_only_columns(
        func.count(WorldInfoEntry.id),
        func.coalesce(func.sum(func.json_array_length(WorldInfoEntry.facts)), 0),
        func.coalesce(
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
            0,
        ),
        func.coalesce(func.sum(case((WorldInfoEntry.status == "draft", 1), else_=0)), 0),
        func.coalesce(func.sum(case((WorldInfoEntry.status == "archived", 1), else_=0)), 0),
        func.coalesce(func.sum(func.length(sql_cast(WorldInfoEntry.search_text, LargeBinary))), 0),
        func.coalesce(func.sum(func.length(WorldInfoEntry.search_text)), 0),
    )
    counts = (await db.execute(entries)).one()
    source_count = int(
        await db.scalar(
            select(func.count(WorldInfoSource.id))
            .join(GameSession, GameSession.id == WorldInfoSource.session_id)
            .where(
                GameSession.user_id == user_id,
                WorldInfoSource.user_id == user_id,
                WorldInfoSource.session_id == session_id,
            )
        )
        or 0
    )
    revisions = (
        await db.execute(
            select(
                func.count(WorldInfoRevision.id),
                func.coalesce(func.sum(WorldInfoRevision.input_bytes), 0),
            )
            .join(WorldInfoSource, WorldInfoSource.id == WorldInfoRevision.source_id)
            .join(GameSession, GameSession.id == WorldInfoSource.session_id)
            .where(
                GameSession.user_id == user_id,
                WorldInfoSource.user_id == user_id,
                WorldInfoSource.session_id == session_id,
                WorldInfoRevision.user_id == user_id,
                WorldInfoRevision.session_id == session_id,
            )
        )
    ).one()
    return OverviewTotals(
        entries=int(counts[0]),
        facts=int(counts[1]),
        active_entries=int(counts[2]),
        draft_entries=int(counts[3]),
        archived_entries=int(counts[4]),
        sources=source_count,
        source_revisions=int(revisions[0]),
        source_bytes=int(revisions[1]),
        entries_bytes=int(counts[5]),
        entries_characters=int(counts[6]),
    )
