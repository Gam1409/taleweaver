"""Owner-visible durable results of the latest item and local-arrival checks."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.auth import get_current_user
from backend.core.database import get_db
from backend.engine.dynamic_locations.schema import registry
from backend.engine.narrated_items.runtime import KEY
from backend.engine.visual_novel.presentation import session_mode
from backend.models.game_session import GameSession
from backend.models.session_state import SessionState
from backend.models.user import User

router = APIRouter(tags=["Gameplay"])


@router.get("/{game_id}/state-checks")
async def state_checks(
    game_id: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
) -> dict:
    session = await db.get(GameSession, game_id)
    if session is None or session.user_id != user.id:
        raise HTTPException(404, "Session not found.")
    state = await db.scalar(select(SessionState).where(SessionState.session_id == game_id))
    if state is None:
        raise HTTPException(404, "Session state not found.")
    raw = (state.entity_states or {}).get(KEY)
    items = raw if isinstance(raw, dict) else {}
    return {
        "mode": await session_mode(db, state),
        "items": {
            "status": items.get("status", "not_run"),
            "reason": items.get("reason", ""),
            "error_type": items.get("error_type", ""),
            "message_id": items.get("message_id", ""),
            "accepted": [
                {
                    "name": row["item"]["name"],
                    "destination": row["destination_owner"],
                    "disposition": row["disposition"],
                }
                for row in items.get("accepted", [])
            ],
            "rejected": items.get("rejected", []),
        },
        "arrival": registry(state).get("last_arrival"),
    }
