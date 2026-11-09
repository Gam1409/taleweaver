"""Bounded chronological wardrobe evidence, optionally fenced at a saved moment."""

from dataclasses import dataclass

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.chat import ChatMessage

MAX_MESSAGES = 80
MAX_CHARACTERS = 48000


@dataclass(frozen=True)
class HistoryWindow:
    messages: list[dict]
    limited: bool
    revisions: tuple[tuple[str, str | None], ...]


async def load_history(
    db: AsyncSession, session_id: str, *, through: ChatMessage | None = None
) -> HistoryWindow:
    query = select(ChatMessage).where(
        ChatMessage.session_id == session_id,
        ChatMessage.role.in_(["user", "assistant"]),
        ~ChatMessage.content.startswith("/debug"),
    )
    if through is not None:
        if (
            through.session_id != session_id
            or through.role != "assistant"
            or not through.id
            or through.created_at is None
        ):
            raise ValueError("Choose a saved narrator message from this session.")
        query = query.where(
            or_(
                ChatMessage.created_at < through.created_at,
                and_(ChatMessage.created_at == through.created_at, ChatMessage.id <= through.id),
            )
        )
    rows = list(
        await db.scalars(
            query.order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc()).limit(
                MAX_MESSAGES + 1
            )
        )
    )
    selected, size = [], 0
    for row in rows[:MAX_MESSAGES]:
        if size + len(row.content) > MAX_CHARACTERS:
            break
        selected.append(row)
        size += len(row.content)
    selected.reverse()
    return HistoryWindow(
        [
            {"id": row.id, "role": row.role, "content": row.content, "scene_id": row.scene_id}
            for row in selected
        ],
        len(rows) > len(selected),
        tuple((row.id, row.revision_id) for row in selected),
    )
