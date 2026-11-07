"""Revalidate saved message anchors; changed sources invalidate their causal suffix."""

from typing import Any

from sqlalchemy import select

from backend.engine.chpm.host_state import Mind, before_messages
from backend.engine.chpm.kernel import digest
from backend.models.chat import ChatMessage


async def reconcile(manager: Any, mind: Mind) -> Mind:
    if not mind.sources:
        return mind
    ids = {source.message_id for source in mind.sources.values()}
    rows = await manager.db.scalars(
        select(ChatMessage).where(
            ChatMessage.session_id == manager.game_id, ChatMessage.id.in_(ids)
        )
    )
    messages = {row.id: row for row in rows}
    return from_messages(mind, messages)


def from_messages(mind: Mind, messages: dict[str, Any]) -> Mind:
    """Reuse a canonical post-await read without replaying invalid dependent suffixes."""
    hashes = {key: digest(row.content) for key, row in messages.items()}
    invalid = set()
    for source in mind.sources.values():
        row = messages.get(source.message_id)
        if (
            row is None
            or (getattr(row, "npc_journal", None) or {}).get("status") == "incomplete"
            or getattr(row, "session_id", mind.genesis.scope.world_id)
            != mind.genesis.scope.world_id
            or row.role != source.role
            or row.revision_id != source.revision_id
            or hashes[source.message_id] != source.content_hash
            or (source.reported and source.evidence_quote not in row.content)
        ):
            invalid.add(source.message_id)
    return before_messages(mind, invalid)
