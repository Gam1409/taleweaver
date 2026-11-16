"""Expose whether the latest answer has a safe pre-action snapshot."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.auth import get_current_user
from backend.core.database import get_db
from backend.engine.turn_replay.service import latest
from backend.models.game_session import GameSession
from backend.models.turn_replay import TurnReplay
from backend.models.user import User

router = APIRouter(tags=["Gameplay"])


@router.get("/{game_id}/chat/replay")
async def replay_status(
    game_id: str, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)
) -> dict:
    session = await db.get(GameSession, game_id)
    if session is None or session.user_id != current_user.id:
        raise HTTPException(404, "Session not found.")
    row = await db.get(TurnReplay, game_id)
    message = await latest(db, game_id)
    available = bool(
        row
        and row.status == "ready"
        and message
        and message.role == "assistant"
        and row.assistant_id == message.id
    )
    return {
        "available": available,
        "message_id": row.assistant_id if available and row is not None else None,
        "reason": None
        if available
        else "No pre-turn snapshot is available for this response. Play a new turn first.",
    }
