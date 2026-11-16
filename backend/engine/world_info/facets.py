"""Bounded SQL facet names and counts, with no full record or source payloads."""

from typing import Any

from sqlalchemy import func, select, true
from sqlalchemy.ext.asyncio import AsyncSession

from backend.engine.world_info.query import entry_query
from backend.engine.world_info.schemas import EntryFacets, EntryFilters, FacetCount, FacetValues
from backend.engine.world_info.types import validate_text
from backend.models.world_info import WorldInfoEntry
from backend.utils.sqlite_text import casefold

MAX_FACETS = 100


async def _values(db: AsyncSession, statement: Any, query: str) -> FacetValues:
    grouped = statement.subquery()
    selected = select(grouped.c.name, grouped.c.count)
    if query.strip():
        selected = selected.where(
            func.tw_casefold(grouped.c.name).contains(casefold(query.strip()), autoescape=True)
        )
    total = int(await db.scalar(select(func.count()).select_from(selected.subquery())) or 0)
    rows = await db.execute(
        selected.order_by(
            grouped.c.count.desc(), func.tw_casefold(grouped.c.name), grouped.c.name
        ).limit(MAX_FACETS)
    )
    return FacetValues(
        items=[FacetCount(name=row[0], count=int(row[1])) for row in rows], total=total
    )


async def entry_facets(
    db: AsyncSession, user_id: str, session_id: str, filters: EntryFilters, *, facet_query: str = ""
) -> EntryFacets:
    """Facet alternatives reflect the view/source/query, independent of selected labels."""
    if len(facet_query) > 200:
        raise ValueError("Facet search exceeds its character budget.")
    validate_text(facet_query)
    scope_filters = filters.model_copy(update={"group_name": None, "tag": None, "kind": None})
    base = await entry_query(db, user_id, session_id, scope_filters)
    scope = (
        base.order_by(None)
        .with_only_columns(
            WorldInfoEntry.id, WorldInfoEntry.group_name, WorldInfoEntry.tags, WorldInfoEntry.kind
        )
        .subquery()
    )
    groups = select(scope.c.group_name.label("name"), func.count().label("count")).group_by(
        scope.c.group_name
    )
    kinds = select(scope.c.kind.label("name"), func.count().label("count")).group_by(scope.c.kind)
    tags = func.json_each(scope.c.tags).table_valued("value")
    tagged = (
        select(tags.c.value.label("name"), func.count(func.distinct(scope.c.id)).label("count"))
        .select_from(scope.join(tags, true()))
        .where(func.typeof(tags.c.value) == "text")
        .group_by(tags.c.value)
    )
    return EntryFacets(
        groups=await _values(db, groups, facet_query),
        tags=await _values(db, tagged, facet_query),
        kinds=await _values(db, kinds, facet_query),
    )
