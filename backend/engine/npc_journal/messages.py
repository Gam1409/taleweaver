"""Copy conversation IDs and durable work consistently when saves are imported or forked."""

from contextlib import suppress
from copy import deepcopy
from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.chat import ChatMessage


def restore_messages(
    db: AsyncSession, session_id: str, messages: list[dict[str, Any]]
) -> dict[str, str]:
    ids: dict[str, str] = {raw["id"]: str(uuid4()) for raw in messages if raw.get("id")}
    for raw in messages:
        message_id = ids.get(raw.get("id"), str(uuid4()))
        journal = deepcopy(raw.get("npc_journal"))
        if isinstance(journal, dict):
            journal["gaps"] = [ids[gap] for gap in journal.get("gaps", []) if gap in ids]
            journal.pop("token", None)
            journal.pop("lease_until", None)
            if journal.get("status") == "running":
                journal.update(status="pending", attempts=0, recovering=True)
        message = ChatMessage(
            id=message_id,
            session_id=session_id,
            role=raw.get("role"),
            content=raw.get("content"),
            scene_id=raw.get("scene_id"),
            sequence_id=raw.get("sequence_id"),
            npc_journal=journal,
        )
        created_at = raw.get("created_at")
        if isinstance(created_at, datetime):
            message.created_at = created_at
        if isinstance(created_at, str):
            with suppress(ValueError):
                message.created_at = datetime.fromisoformat(created_at)
        db.add(message)
    return ids


async def copy_messages(db: AsyncSession, original_id: str, copied_id: str) -> dict[str, str]:
    messages = (
        await db.scalars(
            select(ChatMessage)
            .where(ChatMessage.session_id == original_id)
            .order_by(ChatMessage.created_at, ChatMessage.id)
        )
    ).all()
    return restore_messages(
        db,
        copied_id,
        [
            {
                "id": m.id,
                "role": m.role,
                "content": m.content,
                "created_at": m.created_at,
                "scene_id": m.scene_id,
                "sequence_id": m.sequence_id,
                "npc_journal": m.npc_journal,
            }
            for m in messages
        ],
    )
