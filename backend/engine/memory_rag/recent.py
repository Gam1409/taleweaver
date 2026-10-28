"""Use the same complete-turn boundary for recent context and chronicle compression."""

from typing import Any

from sqlalchemy import and_, or_, select

from backend.models.chat import ChatMessage


def turn_window(state: Any) -> int:
    value = getattr(state, "max_memory_turns", None)
    return max(1, int(value if value is not None else 10))


async def recent_dialogue(db: Any, state: Any) -> list[dict[str, str]]:
    starts = list(
        await db.scalars(
            select(ChatMessage)
            .where(ChatMessage.session_id == state.session_id, ChatMessage.role == "user")
            .order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc())
            .limit(turn_window(state))
        )
    )
    query = select(ChatMessage).where(ChatMessage.session_id == state.session_id)
    if len(starts) == turn_window(state):
        first = starts[-1]
        query = query.where(
            or_(
                ChatMessage.created_at > first.created_at,
                and_(ChatMessage.created_at == first.created_at, ChatMessage.id >= first.id),
            )
        )
    rows = await db.scalars(query.order_by(ChatMessage.created_at, ChatMessage.id))
    return [{"role": row.role, "content": row.content} for row in rows]
