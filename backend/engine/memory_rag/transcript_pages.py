"""Read lightweight transcript columns in bounded keyset pages."""

from types import SimpleNamespace
from typing import Any

from sqlalchemy import and_, or_, select

from backend.models.chat import ChatMessage

PAGE_SIZE = 256


async def transcript_messages(db: Any, session_id: str) -> dict[str, Any]:
    # Exclude revisions, image audit records and other large unrelated JSON columns.
    columns = (
        ChatMessage.id,
        ChatMessage.content,
        ChatMessage.role,
        ChatMessage.scene_id,
        ChatMessage.sequence_id,
        ChatMessage.created_at,
        ChatMessage.npc_journal,
    )
    messages: dict[str, Any] = {}
    cursor = None
    while True:
        query = (
            select(*columns)
            .where(
                ChatMessage.session_id == session_id, ChatMessage.role.in_(["user", "assistant"])
            )
            .order_by(ChatMessage.created_at, ChatMessage.id)
            .limit(PAGE_SIZE)
        )
        if cursor is not None:
            stamp, identifier = cursor
            query = query.where(
                or_(
                    ChatMessage.created_at > stamp,
                    and_(ChatMessage.created_at == stamp, ChatMessage.id > identifier),
                )
            )
        page = (await db.execute(query)).mappings().all()
        if not page:
            return messages
        for row in page:
            if row["content"] and (row["npc_journal"] or {}).get("status") != "incomplete":
                messages[row["id"]] = SimpleNamespace(**row)
        cursor = page[-1]["created_at"], page[-1]["id"]
        if len(page) < PAGE_SIZE:
            return messages
