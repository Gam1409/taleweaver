"""Resolve authoritative session exits before applying deterministic mechanics."""

from fastapi import HTTPException
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.session_state import SessionState
from backend.models.world_entity import WorldExit


async def _resolve_session_exit(
    db: AsyncSession, state: SessionState, exit_id: str
) -> WorldExit | None:
    """Returns the exit used for the current session, preferring the session-scoped row."""
    clean_id = (exit_id or "").strip()
    res = await db.execute(
        select(WorldExit).where(
            or_(
                WorldExit.session_id == state.session_id,
                and_(
                    WorldExit.template_id == state.template_id,
                    WorldExit.session_id.is_(None),
                ),
            ),
            or_(
                WorldExit.id == clean_id,
                func.lower(WorldExit.id) == clean_id.lower(),
            ),
        )
    )
    resolved = res.scalars().first()
    if not resolved:
        return None

    # If it is template-scoped, try to find the corresponding session-scoped exit
    if resolved.session_id is None:
        session_res = await db.execute(
            select(WorldExit).where(
                WorldExit.session_id == state.session_id,
                WorldExit.from_scene_id == resolved.from_scene_id,
                WorldExit.to_scene_id == resolved.to_scene_id,
            )
        )
        session_exit = session_res.scalars().first()
        if session_exit:
            return session_exit

    return resolved


async def _require_session_exit(db: AsyncSession, state: SessionState, exit_id: str) -> WorldExit:
    world_exit = await _resolve_session_exit(db, state, exit_id)
    if not world_exit:
        raise HTTPException(status_code=404, detail="Exit not found.")
    return world_exit
