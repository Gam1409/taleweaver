"""Owner-scoped index controls; canonical game history is never deleted here."""

from sqlalchemy import select
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
    result = []
    for session in sessions:
        row = existing.get(session.id)
        if row is None:
            row = MemoryIndexState(
                session_id=session.id,
                user_id=session.user_id,
                template_id=session.template_id,
                epoch=0,
                desired_revision=1,
                indexed_revision=0,
                paused=False,
                status="pending",
            )
            db.add(row)
        result.append(row)
    await db.flush()
    return result


def invalidate(row: MemoryIndexState, *, paused: bool | None = None) -> None:
    row.epoch += 1
    row.desired_revision += 1
    row.indexed_revision = 0
    row.signature = None
    row.lease_token = None
    row.lease_until = None
    row.last_error = None
    if paused is not None:
        row.paused = paused
    row.status = "paused" if row.paused else "pending"


def schedule_rows(rows: list[MemoryIndexState], *, enabled: bool) -> None:
    if not enabled:
        return
    from backend.engine.memory_rag.worker import schedule

    for row in rows:
        if not row.paused:
            schedule(row.session_id, row.user_id)
