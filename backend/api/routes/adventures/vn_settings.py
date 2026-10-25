"""Owner-scoped narration preferences for Visual Novel sessions."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.auth import get_current_user
from backend.core.database import get_db
from backend.engine.visual_novel.concurrency import (
    BUSY_DETAIL,
    SessionBusyError,
    session_write_lease,
)
from backend.engine.visual_novel.config import VnSettings, read_settings, write_settings
from backend.engine.visual_novel.presentation import session_is_vn
from backend.models.game_session import GameSession
from backend.models.session_state import SessionState
from backend.models.user import User

router = APIRouter(tags=["Visual Novel"])


async def owned_vn_state(db: AsyncSession, game_id: str, user: User) -> SessionState:
    state = await db.scalar(
        select(SessionState)
        .join(GameSession, GameSession.id == SessionState.session_id)
        .where(GameSession.id == game_id, GameSession.user_id == user.id)
    )
    if state is None:
        raise HTTPException(404, "Session not found.")
    if not await session_is_vn(db, state):
        raise HTTPException(409, "Narration pace is available in Visual Novel sessions only.")
    return state


@router.get("/{game_id}/vn-settings")
async def read(
    game_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    state = await owned_vn_state(db, game_id, user)
    return {"settings": read_settings(state).model_dump(), "mode": "vn"}


@router.patch("/{game_id}/vn-settings")
async def update(
    game_id: str,
    payload: VnSettings,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    # Authenticate before checking busy state, without loading mutable session JSON.
    owned_id = await db.scalar(
        select(GameSession.id).where(GameSession.id == game_id, GameSession.user_id == user.id)
    )
    if owned_id is None:
        raise HTTPException(404, "Session not found.")
    try:
        with session_write_lease(game_id):
            state = await owned_vn_state(db, game_id, user)
            write_settings(state, payload)
            await db.commit()
    except SessionBusyError:
        raise HTTPException(409, BUSY_DETAIL) from None
    return {"settings": payload.model_dump(), "mode": "vn"}
