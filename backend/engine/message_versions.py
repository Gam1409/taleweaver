"""Append-only narration history; a restore is a new revision, never a world rewind."""

from copy import deepcopy
from datetime import datetime, timezone
from uuid import uuid4

from backend.models.chat import ChatMessage


def archive(
    message: ChatMessage, content: str, *, origin: str = "rewrite", restored_from: str | None = None
) -> str:
    """Called inside the same transaction as replacement and evidence invalidation."""
    records = deepcopy(message.versions or [])
    previous = message.revision_id or uuid4().hex
    if not any(row.get("id") == previous for row in records):
        records.append(
            {
                "id": previous,
                "content": content,
                "origin": "original",
                "recorded_at": datetime.now(timezone.utc).isoformat(),
            }
        )
    revision = uuid4().hex
    records.append(
        {
            "id": revision,
            "content": message.content,
            "origin": origin,
            "restored_from": restored_from,
            "previous_revision_id": previous,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    message.revision_id = revision
    message.versions = records
    return revision


def history(message: ChatMessage) -> list[dict]:
    records = deepcopy(message.versions or [])
    if not records:
        records = [{"id": message.revision_id, "content": message.content, "origin": "original"}]
    return records
