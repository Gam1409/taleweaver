"""Bound foreground source loading; full corpus scans belong to idle indexing."""

from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import selectinload

from backend.engine.memory_rag.documents import (
    MemoryDocument,
    _bounded_document,
    _dialogue,
    _document,
    _journal_documents,
    _session_documents,
    _world_documents,
    sources_hash,
    summary_sources,
)
from backend.engine.memory_rag.ranking import ordered_terms
from backend.engine.npc_journal.records import journal_of
from backend.models.chat import ChatMessage
from backend.models.game_session import GameSession
from backend.models.memory_rag import MemorySummary
from backend.models.session_state import SessionState
from backend.models.world_entity import WorldEntity

RECENT_MESSAGES = 80
LEXICAL_MESSAGES = 40
MAX_SOURCE_MESSAGES = 320
MAX_NPCS = 20
MAX_SUMMARIES = 12


async def _message_ids(db: Any, sid: str, query: str, candidates: list[dict]) -> set[str]:
    base = (
        select(ChatMessage.id)
        .where(ChatMessage.session_id == sid, ChatMessage.role.in_(["user", "assistant"]))
        .order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc())
    )
    ids = set(await db.scalars(base.limit(RECENT_MESSAGES)))
    terms = ordered_terms(query, 8, minimum=3)
    if terms:
        ids.update(
            await db.scalars(
                base.where(
                    or_(
                        *(
                            func.tw_casefold(ChatMessage.content).contains(term, autoescape=True)
                            for term in terms
                        )
                    )
                ).limit(LEXICAL_MESSAGES)
            )
        )
    semantic_ids = dict.fromkeys(
        str(mid) for row in candidates[:32] for mid in (row.get("source_message_ids") or [])[:32]
    )
    ids.update(list(semantic_ids)[:160])
    return ids


async def _npcs(db: Any, sid: str, npc_ids: set[str], candidates: list[dict]) -> list[Any]:
    wanted = sorted(npc_ids | {str(row["npc_id"]) for row in candidates[:32] if row.get("npc_id")})[
        :MAX_NPCS
    ]
    return list(
        await db.scalars(
            select(WorldEntity)
            .where(
                WorldEntity.session_id == sid,
                WorldEntity.entity_type == "NPC",
            )
            .order_by(WorldEntity.id.in_(wanted).desc(), WorldEntity.id)
            .limit(MAX_NPCS)
            .execution_options(populate_existing=True)
        )
    )


def _journal_source_ids(npcs: list[Any], budget: int) -> set[str]:
    # Round-robin recent evidence across characters without loading their whole chat history.
    if budget <= 0:
        return set()
    ids: set[str] = set()
    groups = [list(reversed(journal_of(npc, full=True).get("entries") or [])) for npc in npcs]
    for offset in range(max((len(group) for group in groups), default=0)):
        ids.update(
            group[offset]["message_id"]
            for group in groups
            if offset < len(group) and group[offset].get("message_id")
        )
        if len(ids) >= budget:
            return set(sorted(ids)[:budget])
    return ids


async def collect_documents(
    db: Any,
    state: Any,
    user_id: str,
    *,
    query: str = "",
    npc_ids: set[str] | None = None,
    candidates: list[dict] | None = None,
) -> list[MemoryDocument]:
    """Validate vector hits against current SQL, with bounded fresh and lexical fallback."""
    current = await db.scalar(
        select(SessionState)
        .join(GameSession, GameSession.id == SessionState.session_id)
        .where(SessionState.session_id == state.session_id, GameSession.user_id == user_id)
        .options(selectinload(SessionState.session))
        .execution_options(populate_existing=True)
    )
    if current is None:
        return []
    candidates = (candidates or [])[:32]
    ids = await _message_ids(db, state.session_id, query, candidates)
    npcs = await _npcs(db, state.session_id, npc_ids or set(), candidates)
    ids.update(_journal_source_ids(npcs, max(0, MAX_SOURCE_MESSAGES - len(ids))))
    summary_ids = [
        str(row.get("source_id", "")).split(":chunk:", 1)[0]
        for row in candidates
        if str(row.get("layer", "")).endswith("_summary")
    ]
    summaries = list(
        await db.scalars(
            select(MemorySummary)
            .where(MemorySummary.session_id == state.session_id, MemorySummary.user_id == user_id)
            .order_by(MemorySummary.id.in_(summary_ids).desc(), MemorySummary.updated_at.desc())
            .limit(MAX_SUMMARIES)
        )
    )
    accepted_summaries = []
    for summary in summaries:
        required = set(summary.source_message_ids or [])
        if required and len(ids | required) <= MAX_SOURCE_MESSAGES:
            ids.update(required)
            accepted_summaries.append(summary)
    rows = await db.scalars(
        select(ChatMessage)
        .where(
            ChatMessage.session_id == state.session_id,
            ChatMessage.id.in_(sorted(ids)),
            ChatMessage.role.in_(["user", "assistant"]),
        )
        .execution_options(populate_existing=True)
    )
    messages = {
        row.id: row
        for row in rows
        if row.content and (row.npc_journal or {}).get("status") != "incomplete"
    }
    documents = [doc for row in messages.values() for doc in _dialogue(current, user_id, row)]
    for npc in npcs:
        documents.extend(_journal_documents(current, user_id, npc, messages))
    documents.extend(_world_documents(current, user_id))
    documents.extend(_session_documents(current, user_id))
    documents = [chunk for doc in documents for chunk in _bounded_document(doc)]
    raw = list(documents)
    for summary in accepted_summaries:
        sources = summary_sources(raw, summary.layer, summary.npc_id, summary.scene_id)
        if (
            not set(summary.source_message_ids) <= messages.keys()
            or sources_hash(sources, summary.source_message_ids, summary.source_keys)
            != summary.source_hash
        ):
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
    return [chunk for doc in documents for chunk in _bounded_document(doc)]
