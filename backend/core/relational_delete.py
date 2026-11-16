"""Delete ownership trees explicitly, including rows without ORM relationships."""

from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.base import Base


async def delete_owned_rows(db: AsyncSession, table: Any, predicate: Any) -> None:
    """Respect SET NULL links; remove dependent rows before their parent."""
    for child in Base.metadata.tables.values():
        for foreign in child.foreign_keys:
            if foreign.column.table is not table:
                continue
            column = foreign.parent
            related = column.in_(select(foreign.column).where(predicate))
            if foreign.ondelete == "SET NULL" or (child is table and column.nullable):
                await db.execute(update(child).where(related).values({column.key: None}))
                continue
            if child is table:
                raise ValueError("Unsupported recursive ownership relation.")
            await delete_owned_rows(db, child, related)
    await db.execute(delete(table).where(predicate))
