"""Retain before-turn world checkpoints only while gameplay Debug is enabled."""

from typing import Any

from sqlalchemy import delete, func, or_, select

from backend.core.config import settings
from backend.engine.session_checkpoint_service import DEBUG_TURN_REASON, SessionCheckpointService
from backend.models.chat import ChatMessage
from backend.models.session_checkpoint import SessionCheckpoint


async def record_before(manager: Any, text: str) -> None:
    state = manager.state
    if not (settings.TALEWEAVER_DEBUG_ENABLED or getattr(state, "is_debug_enabled", False)):
        return
    session_id = manager.game_id
    number = 1 + int(
        await manager.db.scalar(
            select(func.count(ChatMessage.id)).where(
                ChatMessage.session_id == session_id,
                ChatMessage.role == "user",
                or_(
                    ~ChatMessage.content.startswith("/"),
                    func.lower(ChatMessage.content).startswith("/say "),
                ),
            )
        )
        or 0
    )
    await _replace_boundary(manager, number)
    point = await SessionCheckpointService.create_checkpoint(
        manager.db, session_id, DEBUG_TURN_REASON
    )
    point.state_snapshot = {
        **point.state_snapshot,
        "debug_turn": {
            "turn_number": number,
            "input_preview": " ".join(text.split())[:160],
        },
    }


async def _replace_boundary(manager: Any, number: int) -> None:
    points = list(
        await manager.db.scalars(
            select(SessionCheckpoint).where(
                SessionCheckpoint.session_id == manager.game_id,
                SessionCheckpoint.trigger_reason == DEBUG_TURN_REASON,
            )
        )
    )
    stale = [
        point.id
        for point in points
        if not (point.state_snapshot or {}).get("pinned") and _same_turn(point, number)
    ]
    if stale:
        await manager.db.execute(delete(SessionCheckpoint).where(SessionCheckpoint.id.in_(stale)))


def _same_turn(point: SessionCheckpoint, number: int) -> bool:
    info = (point.state_snapshot or {}).get("debug_turn")
    return isinstance(info, dict) and info.get("turn_number") == number
