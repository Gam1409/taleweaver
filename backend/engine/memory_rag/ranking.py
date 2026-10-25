"""Deterministic hybrid relevance; old evidence competes without a recency cutoff."""

import math
import re
from collections import Counter

from backend.engine.memory_rag.documents import MemoryDocument

_STOP_WORDS = frozenset(
    [
        "the",
        "a",
        "an",
        "and",
        "or",
        "to",
        "of",
        "in",
        "is",
        "was",
        "it",
        "you",
        "i",
        "me",
        "my",
        "that",
        "this",
        "with",
        "for",
        "on",
    ]
)
_LAYER_WEIGHT = {
    "npc_journal": 1.8,
    "world_memory": 1.5,
    "session_note": 1.4,
    "npc_summary": 1.0,
    "scene_summary": 0.8,
    "story_summary": 0.7,
    "dialogue": 0.2,
}


def tokens(text: str) -> set[str]:
    return set(re.findall(r"[^\W_]+", text.casefold())) - _STOP_WORDS


def _importance(document: MemoryDocument) -> float:
    # Journal categories are structured English labels, irrespective of story language.
    category = document.text.split(" — ", 1)[-1].split("/", 1)[0]
    if category in {"preference", "relationship", "promise", "background", "personality", "fact"}:
        return 1.7
    if category in {"appearance", "equipment", "belongings"}:
        return -0.9
    return 0.0


def rank_documents(
    documents: list[MemoryDocument],
    query: str,
    npc_ids: set[str],
    scene_id: str,
    semantic_scores: dict[str, float] | None = None,
) -> list[MemoryDocument]:
    """Use IDF overlap, entity/scene anchors, stable facts and a small recency tie-break."""
    if not documents:
        return []
    query_terms = tokens(query)
    vocabulary = {doc.id: tokens(doc.text) for doc in documents}
    frequencies = Counter(term for words in vocabulary.values() for term in words)
    weights = {term: math.log1p(len(documents) / (1 + frequencies[term])) for term in query_terms}
    semantic_scores = semantic_scores or {}
    chronological = sorted(documents, key=lambda doc: (doc.created_at, doc.id))
    recency = {doc.id: position / len(documents) for position, doc in enumerate(chronological)}

    def score(document: MemoryDocument) -> float:
        lexical = sum(weights[word] for word in query_terms & vocabulary[document.id])
        npc = 2.0 if document.npc_id in npc_ids else 0.0
        scene = 0.35 if document.scene_id == scene_id else 0.0
        semantic = max(0.0, min(1.0, semantic_scores.get(document.id, 0.0))) * 4
        if not (lexical or npc or semantic):
            return 0.0
        importance = _LAYER_WEIGHT.get(document.layer, 0.0) + _importance(document)
        return lexical + npc + scene + semantic + importance + recency[document.id] * 0.15

    scored = [(score(doc), doc) for doc in documents]
    return [
        doc for value, doc in sorted(scored, key=lambda pair: (-pair[0], pair[1].id)) if value > 0
    ]
