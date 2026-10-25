"""Canonical, source-backed public memory documents; vectors never own story facts."""

import hashlib
import json
from dataclasses import asdict, dataclass, replace
from typing import Any

from sqlalchemy import select

from backend.engine.npc_journal.records import journal_of, supported_quote
from backend.models.chat import ChatMessage
from backend.models.game_session import GameSession
from backend.models.memory_rag import MemorySummary
from backend.models.session_state import SessionState
from backend.models.world_entity import WorldEntity

DIALOGUE_CHUNK_CHARS = 2500
DIALOGUE_CHUNK_OVERLAP = 200
MAX_UNCHUNKED_CHARS = 12000


@dataclass(frozen=True)
class MemoryDocument:
    id: str
    user_id: str
    session_id: str
    template_id: str | None
    layer: str
    source_id: str
    source_hash: str
    npc_id: str | None
    scene_id: str | None
    text: str
    provenance: str
    source_message_ids: list[str]
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def content_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode()
    ).hexdigest()


def _bounded_document(document: MemoryDocument) -> list[MemoryDocument]:
    """Imported notes and cumulative chronicles also need bounded embedding inputs."""
    if len(document.text) <= MAX_UNCHUNKED_CHARS:
        return [document]
    chunks = []
    for offset in range(0, len(document.text), DIALOGUE_CHUNK_CHARS - DIALOGUE_CHUNK_OVERLAP):
        if offset and offset + DIALOGUE_CHUNK_OVERLAP >= len(document.text):
            break
        source_id = f"{document.source_id}:chunk:{offset}"
        chunks.append(
            replace(
                document,
                id=content_hash([document.session_id, document.layer, source_id]),
                source_id=source_id,
                source_hash=content_hash([document.source_hash, offset]),
                text=document.text[offset : offset + DIALOGUE_CHUNK_CHARS],
            )
        )
    return chunks


def summary_sources(
    documents: list[MemoryDocument], layer: str, npc_id: str | None, scene_id: str | None
) -> list[MemoryDocument]:
    if layer == "npc_summary":
        return [doc for doc in documents if doc.layer == "npc_journal" and doc.npc_id == npc_id]
    if layer == "scene_summary":
        return [doc for doc in documents if doc.layer == "dialogue" and doc.scene_id == scene_id]
    return [doc for doc in documents if doc.layer == "dialogue"]


def sources_hash(documents: list[MemoryDocument], message_ids: list[str]) -> str:
    selected = set(message_ids)
    return content_hash(
        sorted(
            (doc.id, doc.text, doc.provenance, tuple(doc.source_message_ids))
            for doc in documents
            if doc.source_message_ids and set(doc.source_message_ids) <= selected
        )
    )


def _document(state: Any, user_id: str, **fields: Any) -> MemoryDocument:
    source_fingerprint = fields.pop("source_fingerprint", None)
    fields["id"] = content_hash([state.session_id, fields["layer"], fields["source_id"]])
    fields["source_hash"] = content_hash([fields, source_fingerprint, state.template_id])
    return MemoryDocument(
        user_id=user_id, session_id=state.session_id, template_id=state.template_id, **fields
    )


def _dialogue(state: Any, user_id: str, message: ChatMessage) -> list[MemoryDocument]:
    claimed = message.role == "user"
    fingerprint = content_hash(message.content)
    prefix = "Player statement/action (not verified): " if claimed else "Narration: "
    documents = []
    for offset in range(0, len(message.content), DIALOGUE_CHUNK_CHARS - DIALOGUE_CHUNK_OVERLAP):
        if offset and offset + DIALOGUE_CHUNK_OVERLAP >= len(message.content):
            break
        documents.append(
            _document(
                state,
                user_id,
                layer="dialogue",
                source_id=f"{message.id}:{offset}",
                source_fingerprint=fingerprint,
                npc_id=None,
                scene_id=message.scene_id,
                text=prefix + message.content[offset : offset + DIALOGUE_CHUNK_CHARS],
                provenance="claimed" if claimed else "observed",
                source_message_ids=[message.id],
                created_at=message.created_at.isoformat(),
            )
        )
    return documents


def _journal_documents(
    state: Any, user_id: str, npc: WorldEntity, messages: dict[str, ChatMessage]
) -> list[MemoryDocument]:
    documents = []
    for entry in journal_of(npc).get("entries") or []:
        message = messages.get(entry.get("message_id"))
        if not message or message.role != "assistant":
            continue
        if not supported_quote(entry.get("evidence"), message.content) or not entry.get("text"):
            continue
        source = "claimed" if entry.get("source") == "claimed" else "observed"
        documents.append(
            _document(
                state,
                user_id,
                layer="npc_journal",
                source_id=f"{npc.id}:{entry.get('id') or content_hash(entry)}",
                npc_id=npc.id,
                scene_id=message.scene_id,
                text=f"{npc.name} — {entry.get('category', 'event')}/{entry.get('topic', 'general')} ({source}): {entry['text']}\nEvidence: {entry['evidence']}",
                provenance=source,
                source_message_ids=[message.id],
                created_at=message.created_at.isoformat(),
            )
        )
    return documents


def _world_documents(state: Any, user_id: str) -> list[MemoryDocument]:
    documents = []
    for memory in state.world_memories or []:
        if not isinstance(memory, dict) or not memory.get("description"):
            continue
        documents.append(
            _document(
                state,
                user_id,
                layer="world_memory",
                source_id=str(memory.get("id") or content_hash(memory)),
                npc_id=memory.get("npc_id"),
                scene_id=memory.get("scene_id") if memory.get("scope") == "local" else None,
                text=f"World consequence: {memory['description']} (Emotion: {memory.get('emotion', '')})",
                provenance="observed",
                source_message_ids=[],
                created_at=str(memory.get("timestamp") or ""),
            )
        )
    return documents


def _session_documents(state: Any, user_id: str) -> list[MemoryDocument]:
    notes = (state.exit_states or {}).get("__gm_notes__") or []
    documents = [
        _document(
            state,
            user_id,
            layer="session_note",
            source_id=content_hash(note),
            npc_id=None,
            scene_id=None,
            text=f"Session note: {note}",
            provenance="observed",
            source_message_ids=[],
            created_at="",
        )
        for note in notes
        if isinstance(note, str) and note.strip()
    ]
    chronicle = state.compressed_history
    text = chronicle.get("summary") if isinstance(chronicle, dict) else chronicle
    if isinstance(text, str) and text.strip():
        documents.append(
            _document(
                state,
                user_id,
                layer="chronicle_summary",
                source_id="chronicle",
                npc_id=None,
                scene_id=None,
                text=text,
                provenance="summary",
                source_message_ids=[],
                created_at="",
            )
        )
    return documents


async def collect_documents(db: Any, state: Any, user_id: str) -> list[MemoryDocument]:
    """Read current SQL sources with ownership checks, preserving every evidenced topic."""
    owner = await db.scalar(
        select(GameSession.id).where(
            GameSession.id == state.session_id, GameSession.user_id == user_id
        )
    )
    if owner is None:
        return []
    current = await db.scalar(
        select(SessionState)
        .where(SessionState.session_id == state.session_id)
        .execution_options(populate_existing=True)
    )
    if current is None:
        return []
    rows = await db.scalars(
        select(ChatMessage)
        .where(
            ChatMessage.session_id == state.session_id, ChatMessage.role.in_(["user", "assistant"])
        )
        .order_by(ChatMessage.created_at, ChatMessage.id)
        .execution_options(populate_existing=True)
    )
    messages = {message.id: message for message in rows if message.content}
    documents = [
        document
        for message in messages.values()
        for document in _dialogue(current, user_id, message)
    ]
    npcs = await db.scalars(
        select(WorldEntity)
        .where(WorldEntity.session_id == state.session_id, WorldEntity.entity_type == "NPC")
        .execution_options(populate_existing=True)
    )
    for npc in npcs:
        documents.extend(_journal_documents(current, user_id, npc, messages))
    documents.extend(_world_documents(current, user_id))
    documents.extend(_session_documents(current, user_id))
    documents = [chunk for document in documents for chunk in _bounded_document(document)]
    summaries = await db.scalars(
        select(MemorySummary).where(
            MemorySummary.session_id == state.session_id, MemorySummary.user_id == user_id
        )
    )
    raw_documents = list(documents)
    for summary in summaries:
        if not summary.source_message_ids or not set(summary.source_message_ids) <= messages.keys():
            continue
        sources = summary_sources(raw_documents, summary.layer, summary.npc_id, summary.scene_id)
        if sources_hash(sources, summary.source_message_ids) != summary.source_hash:
            continue
        documents.append(
            _document(
                current,
                user_id,
                layer=summary.layer,
                source_id=summary.id,
                npc_id=summary.npc_id,
                scene_id=summary.scene_id,
                text=summary.text,
                provenance="summary",
                source_message_ids=list(summary.source_message_ids),
                created_at=summary.updated_at.isoformat(),
            )
        )
    return [chunk for document in documents for chunk in _bounded_document(document)]


async def validate_candidates(
    db: Any, state: Any, user_id: str, candidates: list[Any]
) -> list[MemoryDocument]:
    """Return canonical text only when the index ID/hash still matches live SQL."""
    canonical = {doc.id: doc for doc in await collect_documents(db, state, user_id)}
    accepted = []
    seen = set()
    for candidate in candidates:
        row = candidate.to_dict() if isinstance(candidate, MemoryDocument) else candidate
        document = canonical.get(row.get("id"))
        if not document or document.id in seen or document.source_hash != row.get("source_hash"):
            continue
        if row.get("user_id") != user_id or row.get("session_id") != state.session_id:
            continue
        accepted.append(document)
        seen.add(document.id)
    return accepted
