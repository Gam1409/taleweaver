"""Owner-only, debug-gated access to persisted scene JSON."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.auth import get_current_user
from backend.core.config import settings
from backend.core.database import get_db
from backend.engine.scene_debug import scene_debug_payload
from backend.models.chat import ChatMessage
from backend.models.game_session import GameSession
from backend.models.session_state import SessionState
from backend.models.user import User

router = APIRouter(tags=["Gameplay"])


@router.get("/{game_id}/scene-debug")
async def scene_debug(
    game_id: str,
    message_id: str | None = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    state = await db.scalar(
        select(SessionState)
        .join(GameSession, GameSession.id == SessionState.session_id)
        .where(GameSession.id == game_id, GameSession.user_id == user.id)
    )
    if state is None:
        raise HTTPException(404, "Session not found.")
    if not (settings.TALEWEAVER_DEBUG_ENABLED or state.is_debug_enabled):
        raise HTTPException(403, "Enable debug mode for this session to inspect scene JSON.")
    recent = list(
        await db.scalars(
            select(ChatMessage)
            .where(ChatMessage.session_id == game_id, ChatMessage.role == "assistant")
            .order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc())
            .limit(100)
        )
    )
    selected = recent[0] if recent else None
    if message_id is not None:
        selected = await db.scalar(
            select(ChatMessage).where(
                ChatMessage.session_id == game_id,
                ChatMessage.id == message_id,
                ChatMessage.role == "assistant",
            )
        )
        if selected is None:
            raise HTTPException(404, "Narrator message not found in this session.")
    return await scene_debug_payload(db, state, selected, recent)
