"""One bounded recall per turn; optional vectors and authoritative SQL fallback."""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select

from backend.core.llm_logger import log_structured_event
from backend.engine.memory_rag.core import context_fallback, working_memory
from backend.engine.memory_rag.documents import MemoryDocument, collect_documents
from backend.engine.memory_rag.embeddings import embed_texts
from backend.engine.memory_rag.ranking import rank_documents
from backend.engine.memory_rag.settings import embedding_signature, read_settings
from backend.engine.memory_rag.store import LanceMemoryStore, Scope
from backend.models.memory_rag import MemoryIndexState

logger = logging.getLogger(__name__)
VECTOR_SEARCH_GRACE = 0.5


@dataclass
class TurnRecall:
    enabled: bool = False
    documents: list[MemoryDocument] = field(default_factory=list)
    method: str = "disabled"
    elapsed_ms: float = 0
    usage: dict[str, dict] = field(default_factory=dict)
    core_documents: list[MemoryDocument] = field(default_factory=list)

    def record_usage(
        self, manager: Any, audience: str, block: str, selected: list[MemoryDocument]
    ) -> None:
        audit = {
            "retrieval_method": self.method,
            "duration_ms": self.elapsed_ms,
            "source_ids": [doc.source_id for doc in selected],
            "source_message_ids": sorted(
                {mid for doc in selected for mid in doc.source_message_ids}
            ),
            "layers": [doc.layer for doc in selected],
            "chars": len(block),
        }
        if self.usage.get(audience) == audit:
            return
        self.usage[audience] = audit
        log_structured_event(
            "gm.turn.memory_recall",
            game_id=manager.state.session_id,
            message_id=getattr(manager, "_vn_player_message_id", None),
            audience=audience,
            **audit,
        )


async def _index_state(manager: Any) -> Any:
    return await manager.db.scalar(
        select(MemoryIndexState)
        .where(
            MemoryIndexState.session_id == manager.state.session_id,
            MemoryIndexState.user_id == manager.user.id,
        )
        .execution_options(populate_existing=True)
    )


async def _query_vectors(manager: Any, query: str, scope: Scope, settings: Any) -> list[dict]:
    vectors = await embed_texts(manager.user, [query[:4000]], timeout=settings.timeout_seconds)
    if embedding_signature(settings, len(vectors[0])) != scope.signature:
        return []
    return await LanceMemoryStore().query(scope, vectors[0], query, limit=32)


async def _semantic_candidates(manager: Any, query: str) -> tuple[list[dict], Scope | None]:
    index = await _index_state(manager)
    if index is None or index.paused or not index.signature:
        return [], None
    # The first committed batch is usable while remaining sources/summaries build.
    # Fresh SQL below supplies unindexed facts and rejects stale cached sources.
    if not index.indexed_revision and index.status not in {"indexing", "pending"}:
        return [], None
    if index.template_id != manager.state.template_id:
        return [], None
    scope = Scope(str(manager.user.id), str(manager.state.session_id), index.epoch, index.signature)
    query_settings = read_settings(manager.user)
    try:
        candidates = await asyncio.wait_for(
            _query_vectors(manager, query, scope, query_settings),
            query_settings.timeout_seconds + VECTOR_SEARCH_GRACE,
        )
    except Exception as exc:
        # Provider errors can contain credentials or quoted text. Log only the class.
        logger.debug("Memory vectors unavailable (%s); using SQL recall", type(exc).__name__)
        return [], None
    return candidates, scope


def _canonical_scores(
    documents: list[MemoryDocument], candidates: list[dict], scope: Scope
) -> dict[str, float]:
    canonical = {doc.id: doc for doc in documents}
    scores = {}
    for rank, candidate in enumerate(candidates):
        document = canonical.get(candidate.get("id"))
        if document is None or document.source_hash != candidate.get("source_hash"):
            continue
        expected = (
            scope.user_id,
            scope.session_id,
            document.template_id or "",
            scope.epoch,
            scope.signature,
        )
        actual = tuple(
            candidate.get(key)
            for key in ("user_id", "session_id", "template_id", "epoch", "signature")
        )
        if actual != expected:
            continue
        scores[document.id] = 1 / (1 + rank * 0.15)
    return scores


async def _collect_recall(manager: Any, query: str, npc_ids: set[str]) -> TurnRecall:
    candidates, scope = await _semantic_candidates(manager, query)
    # Read source text AFTER network awaits: edits/deletion/rewinds cannot resurrect vector text.
    documents = await collect_documents(manager.db, manager.state, str(manager.user.id))
    scores = {}
    if candidates and scope:
        current = await _index_state(manager)
        if (
            current
            and not current.paused
            and (current.epoch, current.signature) == (scope.epoch, scope.signature)
        ):
            scores = _canonical_scores(documents, candidates, scope)
    ranked = rank_documents(documents, query, npc_ids, manager.state.current_scene_id, scores)
    core = working_memory(documents, npc_ids)
    if not ranked:
        ranked = context_fallback(documents)
    return TurnRecall(
        enabled=True,
        documents=ranked,
        core_documents=core,
        method="hybrid" if scores else "sql_lexical",
    )


async def prepare_recall(
    manager: Any, user_msg: str, entities: list[Any], *, history: list[dict] | None = None
) -> TurnRecall:
    """Cache the result through state-context rebuilds and every actual turn audience."""
    token = (manager.state.session_id, getattr(manager, "_vn_player_message_id", None), user_msg)
    if getattr(manager, "_memory_recall_token", None) == token:
        return manager._memory_recall
    started = time.perf_counter()
    recall = TurnRecall()
    try:
        if read_settings(manager.user).enabled:
            npcs = [entity for entity in entities if entity.entity_type == "NPC"]
            names = " ".join(str(npc.name or npc.id) for npc in npcs)
            previous = " ".join(str(row.get("content", "")) for row in (history or [])[-2:])
            query = user_msg[:2400] + "\nRecent context: " + previous[-1000:]
            query += "\nPresent characters: " + names[:500]
            recall = await _collect_recall(manager, query, {str(npc.id) for npc in npcs})
    except Exception as exc:
        logger.warning(
            "Memory recall unavailable (%s); preserving legacy context", type(exc).__name__
        )
    recall.elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
    manager._memory_recall_token = token
    manager._memory_recall = recall
    return recall
