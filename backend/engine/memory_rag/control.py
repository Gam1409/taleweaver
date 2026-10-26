"""Owner-scoped index controls; canonical game history is never deleted here."""

from sqlalchemy import case, select, update
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.game_session import GameSession
from backend.models.memory_rag import MemoryIndexState


async def ensure_index_states(
    db: AsyncSession, *, user_id: str | None = None, template_id: str | None = None
) -> list[MemoryIndexState]:
    query = select(GameSession)
    if user_id is not None:
        query = query.where(GameSession.user_id == user_id)
    if template_id is not None:
        query = query.where(GameSession.template_id == template_id)
    sessions = list((await db.scalars(query)).all())
    if not sessions:
        return []
    existing = {
        row.session_id: row
        for row in await db.scalars(
            select(MemoryIndexState).where(
                MemoryIndexState.session_id.in_([s.id for s in sessions])
            )
        )
    }
    for session in sessions:
        if session.id in existing:
            continue
        # A foreground dirty marker may insert the same row after our SELECT.
        await db.execute(
            insert(MemoryIndexState)
            .values(session_id=session.id, user_id=session.user_id, template_id=session.template_id)
            .on_conflict_do_nothing(index_elements=[MemoryIndexState.session_id])
        )
    return list(
        await db.scalars(
            select(MemoryIndexState)
            .where(MemoryIndexState.session_id.in_([s.id for s in sessions]))
            .execution_options(populate_existing=True)
        )
    )


async def invalidate(
    db: AsyncSession, row: MemoryIndexState, *, paused: bool | None = None
) -> None:
    # Increment in SQL: concurrent controls must never reuse an epoch or erase a
    # newly queued revision by writing values from an older ORM snapshot.
    values = {
        "epoch": MemoryIndexState.epoch + 1,
        "desired_revision": MemoryIndexState.desired_revision + 1,
        "indexed_revision": 0,
        "signature": None,
        "lease_token": None,
        "lease_until": None,
        "last_error": None,
        "status": case((MemoryIndexState.paused.is_(True), "paused"), else_="pending"),
    }
    if paused is not None:
        values.update(paused=paused, status="paused" if paused else "pending")
    await db.execute(
        update(MemoryIndexState)
        .where(
            MemoryIndexState.session_id == row.session_id, MemoryIndexState.user_id == row.user_id
        )
        .values(**values)
        .execution_options(synchronize_session=False)
    )
    await db.refresh(row)


def schedule_rows(rows: list[MemoryIndexState], *, enabled: bool) -> None:
    if not enabled:
        return
    from backend.engine.memory_rag.worker import schedule

    for row in rows:
        if not row.paused:
            schedule(row.session_id, row.user_id)
