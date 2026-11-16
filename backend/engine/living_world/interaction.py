"""Defer background moves near an ongoing player interaction; never gate turn actions."""

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.engine.living_world.schema import Event
from backend.engine.visual_novel.scene_focus import focus_context
from backend.models.chat import ChatMessage
from backend.models.session_state import SessionState

RECENT_SECONDS = 60
FOCUS_SECONDS = 300
MAX_DEFERRALS = 3


async def defer_move(db: AsyncSession, state: SessionState, event: Event, origin: str) -> bool:
    if state.current_scene_id not in {origin, event.destination}:
        return False
    latest = await db.scalar(
        select(ChatMessage)
        .where(
            ChatMessage.session_id == state.session_id,
            ChatMessage.role == "assistant",
            ChatMessage.is_debug.is_(False),
            ChatMessage.scene_id == state.current_scene_id,
        )
        .order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc())
        .limit(1)
    )
    if latest is None:
        return False
    age = (
        datetime.now(timezone.utc) - latest.created_at.replace(tzinfo=timezone.utc)
    ).total_seconds()
    focus = focus_context(state)
    threshold = FOCUS_SECONDS if focus.get("open_question") else RECENT_SECONDS
    if age >= threshold:
        return False
    event.deferrals += 1
    event.observed_by_player = True
    if event.deferrals >= MAX_DEFERRALS:
        event.status = "CANCELLED"
        event.result = "A background movement was abandoned to let the current scene continue."
    else:
        event.status = "DEFERRED"
        event.retry_after = datetime.now(timezone.utc).timestamp() + RECENT_SECONDS
        event.result = "A background movement is waiting for the current scene to settle."
    return True
