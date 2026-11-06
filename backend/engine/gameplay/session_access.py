"""Resolve session state through the canonical owner-scoped contract."""

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from backend.engine.gameplay.world import AdventureLogic
from backend.models.session_state import SessionState
from backend.models.user import User


async def _require_session_state(
    db: AsyncSession, game_id: str, current_user: User
) -> SessionState:
    state = await AdventureLogic.resolve_session_state(db, game_id, user_id=current_user.id)
    if not state:
        raise HTTPException(status_code=404, detail="Session not found.")
    return state
