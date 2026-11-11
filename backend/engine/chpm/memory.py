"""Bounded witnessed quotations, never beliefs or independent world evidence."""

from typing import Any

from sqlalchemy import select

from backend.engine.chpm.kernel import digest
from backend.engine.chpm.schema import KernelState, MemoryEntry
from backend.engine.debug_transcript import is_debug_message
from backend.models.chat import ChatMessage


async def recall(
    manager: Any, actor_id: str, entries: list[MemoryEntry], limit: int
) -> list[MemoryEntry]:
    if not entries or limit == 0:
        return []
    candidates = entries[-limit:]
    sources = await manager.db.scalars(
        select(ChatMessage).where(
            ChatMessage.session_id == manager.game_id,
            ChatMessage.id.in_({entry.source_message_id for entry in candidates}),
        )
    )
    by_id = {source.id: source for source in sources}
    return [
        entry
        for entry in candidates
        if valid_source(entry, by_id.get(entry.source_message_id), actor_id, manager.game_id)
    ]


def valid_source(entry: MemoryEntry, source: Any, actor_id: str, session_id: str) -> bool:
    return bool(
        source is not None
        and not is_debug_message(source)
        and source.session_id == session_id
        and source.role == entry.source_role
        and entry.observer_id == actor_id
        and source.revision_id == entry.source_revision_id
        and digest(source.content) == entry.source_hash
        and entry.quote in source.content
    )


def append(state: KernelState, actor_id: str, additions: list[MemoryEntry]) -> None:
    """Eviction is an explicit transcript-window policy, not deletion of obligations."""
    entries = list(state.memories.get(actor_id, []))
    keys = {_key(entry) for entry in entries}
    for entry in additions:
        if entry.observer_id == actor_id and _key(entry) not in keys:
            entries.append(entry)
            keys.add(_key(entry))
    limit = state.settings.memory_limit
    state.usage.memory_evictions += max(0, len(entries) - limit)
    state.memories[actor_id] = entries[-limit:] if limit else []


def _key(entry: MemoryEntry) -> tuple[str, str | None, str, str]:
    return entry.source_message_id, entry.source_revision_id, entry.speaker_id, entry.quote


def from_source(
    source: Any, observer_id: str, speaker_id: str, quote: str, kind: str
) -> MemoryEntry:
    return MemoryEntry.model_validate(
        {
            "source_message_id": source.id,
            "source_revision_id": source.revision_id,
            "source_hash": digest(source.content),
            "source_role": source.role,
            "scene_id": source.scene_id or "",
            "observer_id": observer_id,
            "speaker_id": speaker_id,
            "kind": kind,
            "quote": quote,
        }
    )
