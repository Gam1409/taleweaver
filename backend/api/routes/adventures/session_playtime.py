"""Track visible session time independently from the fictional game clock."""

import time

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.auth import get_current_user
from backend.core.database import get_db
from backend.models.game_session import GameSession
from backend.models.user import User

router = APIRouter(tags=["Sessions"])
MAX_HEARTBEAT_GAP_SECONDS = 45


class PlaytimeHeartbeat(BaseModel):
    """Start establishes a baseline; inactive closes the current visible interval."""

    active: bool = True
    start: bool = False


def elapsed_playtime(last_seen: int | None, now: int, *, start: bool) -> int:
    """Discard offline/suspended intervals and never accept client-supplied durations."""
    if start or last_seen is None:
        return 0
    elapsed = now - last_seen
    return elapsed if 0 < elapsed <= MAX_HEARTBEAT_GAP_SECONDS else 0


@router.post("/sessions/{game_id}/playtime")
async def record_playtime(
    game_id: str,
    payload: PlaytimeHeartbeat,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, bool]:
    """Update only timing columns, without acquiring the long-running game-turn lease."""
    session = await db.get(GameSession, game_id)
    if session is None or session.user_id != current_user.id:
        raise HTTPException(404, "Session not found.")
    now = int(time.time())
    elapsed = elapsed_playtime(session.playtime_last_seen, now, start=payload.start)
    # Compare-and-swap prevents overlapping tabs from counting the same interval twice.
    await db.execute(
        update(GameSession)
        .where(
            GameSession.id == game_id,
            GameSession.playtime_last_seen == session.playtime_last_seen,
        )
        .values(
            playtime_seconds=GameSession.playtime_seconds + elapsed,
            playtime_last_seen=now if payload.active else None,
            updated_at=session.updated_at,
        )
    )
    await db.commit()
    return {"ok": True}
