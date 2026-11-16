"""SQL audience authority applied before reference candidate limits."""

from typing import Any

from sqlalchemy import and_, exists, func, or_, select

from backend.engine.world_info import limits
from backend.models.world_entity import WorldEntity
from backend.models.world_info import WorldInfoEntry


def _members(column: Any) -> Any:
    return func.json_each(column).table_valued("value", "type")


def _valid_array(column: Any) -> Any:
    members = _members(column)
    return and_(
        func.json_type(column) == "array",
        func.json_array_length(column) <= limits.MAX_KNOWN_BY,
        ~exists(select(1).select_from(members).where(members.c.type != "text")),
        select(func.count(func.distinct(members.c.value))).select_from(members).scalar_subquery()
        == func.json_array_length(column),
    )


def predicate(session_id: str, actor_id: str) -> Any:
    """Reject malformed, dormant and foreign recipients before any SQL bound."""
    known = _members(WorldInfoEntry.known_by)
    unresolved = _members(WorldInfoEntry.unresolved_known_by)
    actual = exists(
        select(1).where(
            WorldEntity.session_id == session_id,
            WorldEntity.entity_type == "NPC",
            WorldEntity.id == actor_id,
        )
    )
    assigned = exists(select(1).select_from(known).where(known.c.value == actor_id))
    dormant = exists(select(1).select_from(unresolved).where(unresolved.c.value == actor_id))
    unknown = exists(
        select(1).select_from(unresolved).where(unresolved.c.value.not_in(select(known.c.value)))
    )
    return and_(
        actual,
        _valid_array(WorldInfoEntry.known_by),
        _valid_array(WorldInfoEntry.unresolved_known_by),
        ~unknown,
        or_(
            and_(
                WorldInfoEntry.audience == "common_knowledge",
                func.json_array_length(WorldInfoEntry.known_by) == 0,
            ),
            and_(WorldInfoEntry.audience == "restricted", assigned, ~dormant),
        ),
    )
