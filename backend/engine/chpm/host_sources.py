"""Revalidate saved message anchors; changed sources invalidate their causal suffix."""

from typing import Any

from sqlalchemy import select

from backend.engine.chpm import recent_scene
from backend.engine.chpm.host_state import Mind, before_messages
from backend.engine.chpm.kernel import digest
from backend.models.chat import ChatMessage


async def reconcile(manager: Any, mind: Mind) -> Mind:
    if not mind.sources:
        return mind
    ids = {key for source in mind.sources.values() for key in recent_scene.dependencies(source)}
    rows = await manager.db.scalars(
        select(ChatMessage).where(
            ChatMessage.session_id == manager.game_id, ChatMessage.id.in_(ids)
        )
    )
    messages = {row.id: row for row in rows}
    return from_messages(mind, messages)


def from_messages(mind: Mind, messages: dict[str, Any]) -> Mind:
    """Reuse a canonical post-await read without replaying invalid dependent suffixes."""
    from backend.engine.chpm import reports

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
            or (
                source.history is not None
                and (
                    source.history.scene_id != row.scene_id
                    or not source.history.evidence_span.matches(row.content, source.text)
                )
            )
        ):
            invalid.add(source.message_id)
        moment = source.facts.last_observed_scene if source.facts else None
        if not reports.matches(source, messages, mind.genesis.scope.world_id, hashes):
            invalid.add(source.message_id)
        if moment and not recent_scene.matches(
            moment, messages.get(moment.source_message_id), mind.genesis.scope.world_id
        ):
            invalid.add(moment.source_message_id)
    return before_messages(mind, invalid)
