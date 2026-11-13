"""Reconcile only journal-referenced sources when a checkpoint retains rewritten chat.

New checkpoints store revision/hash anchors without duplicating narration. Legacy
checkpoints keep matching evidence; available quotations and the existing private
source owners establish what can be retained when no saved revision is available.
"""

import hashlib
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.engine.debug_transcript import is_debug_message
from backend.engine.narration_evidence import retract_evidence
from backend.engine.npc_journal.archive import expanded
from backend.engine.npc_journal.records import supported_quote
from backend.models.chat import ChatMessage
from backend.models.game_session import GameSession

KEY = "source_revisions"
_BATCH_SIZE = 256


def _journals(snapshot: dict) -> list[dict]:
    return [
        expanded(journal)
        for actor in snapshot.get("canonical_actors", [])
        if isinstance(journal := (actor.get("metadata_json") or {}).get("npc_journal"), dict)
    ]


def _referenced(journals: list[dict]) -> set[str]:
    return {
        source
        for journal in journals
        for source in (
            journal.get("introduced_message_id"),
            journal.get("description_source"),
            *(entry.get("message_id") for entry in journal.get("entries") or []),
            *(journal.get("alias_sources") or {}).values(),
        )
        if isinstance(source, str) and source
    }


async def _messages(db: AsyncSession, session_id: str, identifiers: set[str]) -> dict:
    ordered = sorted(identifiers)
    result: dict[str, ChatMessage] = {}
    for start in range(0, len(ordered), _BATCH_SIZE):
        rows = await db.scalars(
            select(ChatMessage)
            .where(
                ChatMessage.session_id == session_id,
                ChatMessage.id.in_(ordered[start : start + _BATCH_SIZE]),
            )
            .execution_options(populate_existing=True)
        )
        result.update((row.id, row) for row in rows)
    return result


def _anchor(message: ChatMessage | None) -> dict | None:
    if message is None or message.role != "assistant" or is_debug_message(message):
        return None
    return {
        "revision_id": message.revision_id,
        "content_hash": hashlib.sha256(message.content.encode()).hexdigest(),
    }


async def capture(db: AsyncSession, session_id: str, snapshot: dict) -> dict:
    identifiers = _referenced(_journals(snapshot))
    messages = await _messages(db, session_id, identifiers)
    return {identifier: _anchor(messages.get(identifier)) for identifier in sorted(identifiers)}


def validate(snapshot: dict) -> None:
    if KEY not in snapshot:
        return
    anchors = snapshot[KEY]
    if not isinstance(anchors, dict) or any(
        not isinstance(key, str) or not key or not _valid_anchor(value)
        for key, value in anchors.items()
    ):
        raise ValueError("Invalid checkpoint source revisions.")


def _valid_anchor(value: Any) -> bool:
    return value is None or (
        isinstance(value, dict)
        and set(value) == {"revision_id", "content_hash"}
        and (value["revision_id"] is None or isinstance(value["revision_id"], str))
        and isinstance(value["content_hash"], str)
        and len(value["content_hash"]) == 64
        and all(character in "0123456789abcdef" for character in value["content_hash"])
    )


def _legacy_changed(journals: list[dict], messages: dict) -> set[str]:
    changed = {
        identifier
        for identifier in _referenced(journals)
        if _anchor(messages.get(identifier)) is None
    }
    changed.update(
        entry["message_id"]
        for journal in journals
        for entry in journal.get("entries") or []
        if entry.get("message_id") in messages
        and entry.get("evidence")
        and not supported_quote(entry["evidence"], messages[entry["message_id"]].content)
    )
    return changed


async def reconcile(
    db: AsyncSession, session: GameSession, snapshot: dict, *, requeued: list[str] | None = None
) -> None:
    journals = _journals(snapshot)
    messages = await _messages(db, session.id, _referenced(journals))
    if KEY in snapshot:
        changed = {
            identifier
            for identifier, anchor in snapshot[KEY].items()
            if anchor is None or anchor != _anchor(messages.get(identifier))
        }
    else:
        changed = _legacy_changed(journals, messages)
    for identifier in sorted(changed):
        message = messages.get(identifier)
        await retract_evidence(db, session, identifier, message=message)
        if requeued is not None and message is not None and message.npc_journal is not None:
            requeued.append(identifier)
