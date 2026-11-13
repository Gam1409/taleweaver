"""Bounded executemany writes reuse the caller's serialized owner transaction."""

from collections.abc import Sequence
from typing import Any, cast

from sqlalchemy import Table, bindparam
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import set_committed_value

from backend.engine.world_info.access import WorldInfoError
from backend.models.world_info import WorldInfoEntry


async def update_entries(
    db: AsyncSession, user_id: str, session_id: str, changes: Sequence[dict[str, Any]]
) -> None:
    if not changes:
        return
    columns = set(changes[0]) - {"old_id", "old_version"}
    if any(set(row) - {"old_id", "old_version"} != columns for row in changes):
        raise WorldInfoError("Bulk entry fields do not match.")
    table = cast(Table, WorldInfoEntry.__table__)
    statement = (
        table.update()
        .where(
            table.c.id == bindparam("old_id"),
            table.c.version == bindparam("old_version"),
            table.c.user_id == user_id,
            table.c.session_id == session_id,
        )
        .values({column: bindparam(column) for column in columns})
    )
    result = await db.execute(statement, list(changes))
    if cast(CursorResult[Any], result).rowcount != len(changes):
        raise WorldInfoError("Knowledge changed. Preview this selection again.", 409)
    by_id = {row["old_id"]: row for row in changes}
    for row in db.identity_map.values():
        if not isinstance(row, WorldInfoEntry) or row.id not in by_id:
            continue
        for column in columns:
            set_committed_value(row, column, by_id[row.id][column])
