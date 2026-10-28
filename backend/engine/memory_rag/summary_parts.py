"""Bounded fragment coverage: long messages are summarized progressively, never skipped."""

import json
from typing import Any

from backend.engine.memory_rag.documents import MemoryDocument, sources_hash


def pending_parts(
    sources: list[MemoryDocument], existing: list[Any]
) -> tuple[list[MemoryDocument], bool]:
    covered: set[str] = set()
    started: set[str] = set()
    for summary in existing:
        keys = getattr(summary, "source_keys", None)
        if sources_hash(sources, summary.source_message_ids, keys) != summary.source_hash:
            continue
        started.update(summary.source_message_ids)
        if keys is not None:
            covered.update(keys)
        else:
            covered.update(
                doc.source_id
                for doc in sources
                if set(doc.source_message_ids) <= set(summary.source_message_ids)
            )

    pending = [doc for doc in sources if doc.source_id not in covered]
    continuing = any(set(doc.source_message_ids) & started for doc in pending)
    return pending, continuing


def bounded_parts(
    sources: list[MemoryDocument], max_chars: int, max_events: int
) -> tuple[list[MemoryDocument], str]:
    selected: list[MemoryDocument] = []
    rows: list[dict] = []
    message_ids: set[str] = set()
    for doc in sources:
        new_ids = message_ids | set(doc.source_message_ids)
        if len(new_ids) > max_events:
            break
        row = {
            "source_message_ids": doc.source_message_ids,
            "source_key": doc.source_id,
            "text": doc.text,
        }
        if len(json.dumps([*rows, row], ensure_ascii=False)) > max_chars:
            break
        rows.append(row)
        selected.append(doc)
        message_ids = new_ids
    return selected, json.dumps(rows, ensure_ascii=False)


async def language_instruction(db: Any, session_id: str, user: Any) -> str:
    from backend.core.content_language import prose_language_instruction
    from backend.models.game_session import GameSession

    session = await db.get(GameSession, session_id)
    language = (
        (session.content_language if session else None)
        or getattr(user, "default_language", None)
        or "English"
    )
    return prose_language_instruction(language, "summary text")
