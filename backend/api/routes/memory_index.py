"""Explicitly scoped index maintenance; deleting embeddings never deletes story data."""

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.auth import get_current_user
from backend.core.database import get_db
from backend.engine.memory_rag.control import ensure_index_states, invalidate, schedule_rows
from backend.engine.memory_rag.settings import read_settings
from backend.engine.memory_rag.store import LanceMemoryStore
from backend.models.adventure_template import AdventureTemplate
from backend.models.game_session import GameSession
from backend.models.memory_rag import MemoryIndexState
from backend.models.user import User

router = APIRouter(prefix="/adventures/templates", tags=["Memory"])
logger = logging.getLogger(__name__)


async def owned_template(db: AsyncSession, user: User, template_id: str) -> None:
    exists = await db.scalar(
        select(AdventureTemplate.id).where(
            AdventureTemplate.id == template_id, AdventureTemplate.owner_id == user.id
        )
    )
    if exists is None:
        raise HTTPException(404, "Adventure not found.")


@router.get("/{template_id}/memory-index")
async def memory_index_status(
    template_id: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
) -> dict:
    await owned_template(db, user, template_id)
    sessions = list(
        await db.scalars(
            select(GameSession.id).where(
                GameSession.template_id == template_id, GameSession.user_id == user.id
            )
        )
    )
    rows = list(
        await db.scalars(
            select(MemoryIndexState).where(
                MemoryIndexState.session_id.in_(sessions), MemoryIndexState.user_id == user.id
            )
        )
    )
    enabled = read_settings(user).enabled
    paused = bool(rows) and all(row.paused for row in rows)
    pending = (
        len(sessions)
        - len(rows)
        + sum(not row.paused and row.indexed_revision < row.desired_revision for row in rows)
    )
    count = None
    try:
        count = await asyncio.wait_for(LanceMemoryStore().count_template(user.id, template_id), 3)
    except Exception:
        logger.debug("Memory index count unavailable")
    status = (
        "disabled" if not enabled else "paused" if paused else "pending" if pending else "ready"
    )
    return {
        "enabled": enabled,
        "status": status,
        "session_count": len(sessions),
        "pending_count": pending,
        "indexed_count": count,
        "paused": paused,
    }


async def reset_index(db: AsyncSession, user: User, template_id: str, *, paused: bool) -> list:
    await owned_template(db, user, template_id)
    rows = await ensure_index_states(db, user_id=user.id, template_id=template_id)
    for row in rows:
        await invalidate(db, row, paused=True)
    # Publish generation fences before any physical deletion or worker rescheduling.
    await db.commit()
    for row in rows:
        locked = await db.execute(
            update(MemoryIndexState)
            .where(
                MemoryIndexState.session_id == row.session_id,
                MemoryIndexState.user_id == user.id,
                MemoryIndexState.epoch == row.epoch,
                MemoryIndexState.paused.is_(True),
            )
            .values(status="paused")
            .execution_options(synchronize_session=False)
        )
        if locked.rowcount != 1:
            await db.rollback()
            raise HTTPException(409, "Index settings changed during cleanup. Please retry.")
    try:
        await asyncio.wait_for(LanceMemoryStore().delete_template(user.id, template_id), 15)
    except Exception as exc:
        await db.rollback()
        logger.warning("Memory index clearing failed: %s", type(exc).__name__)
        raise HTTPException(
            503, "Index generation was invalidated, but disk cleanup failed. Please retry."
        ) from exc
    if not paused:
        for row in rows:
            changed = await db.execute(
                update(MemoryIndexState)
                .where(
                    MemoryIndexState.session_id == row.session_id,
                    MemoryIndexState.user_id == user.id,
                    MemoryIndexState.epoch == row.epoch,
                    MemoryIndexState.paused.is_(True),
                )
                .values(paused=False, status="pending")
                .execution_options(synchronize_session=False)
            )
            if changed.rowcount != 1:
                await db.rollback()
                raise HTTPException(409, "Index settings changed during cleanup. Please retry.")
        await db.commit()
        for row in rows:
            await db.refresh(row)
    await db.commit()
    return rows


@router.delete("/{template_id}/memory-index")
async def clear_memory_index(
    template_id: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
) -> dict:
    rows = await reset_index(db, user, template_id, paused=True)
    return {"cleared": True, "session_count": len(rows), "paused": True}


@router.post("/{template_id}/memory-index/rebuild")
async def rebuild_memory_index(
    template_id: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
) -> dict:
    if not read_settings(user).enabled:
        raise HTTPException(400, "Enable and configure memory embeddings before rebuilding.")
    rows = await reset_index(db, user, template_id, paused=False)
    schedule_rows(rows, enabled=True)
    return {"queued": True, "session_count": len(rows)}
