"""Small, source-backed working memory; the complete journal stays in SQL."""

from collections import defaultdict
from itertools import zip_longest

from backend.engine.memory_rag.documents import MemoryDocument

_IMPORTANCE = {
    "boundary": 5,
    "commitment": 4,
    "relationship_change": 3,
    "decision": 2,
    "durable_fact": 1,
}


def fact_key(doc: MemoryDocument) -> tuple[str | None, str, str]:
    category = doc.category or doc.text.split(" — ", 1)[-1].split("/", 1)[0]
    topic = doc.topic
    if not topic and "/" in doc.text:
        topic = doc.text.split("/", 1)[1].split(" (", 1)[0]
    # Legacy general mixes unrelated subjects: never collapse it into one fact.
    if not topic or topic == "general":
        return doc.npc_id, category, doc.text.casefold()
    if category in {"appearance", "equipment", "belongings"}:
        category = "physical"
    return doc.npc_id, category, topic


def latest_facts(documents: list[MemoryDocument]) -> dict[tuple, MemoryDocument]:
    facts = {}
    for doc in sorted(documents, key=lambda d: (d.created_at, d.source_message_ids, d.id)):
        if doc.layer == "npc_journal":
            facts[fact_key(doc)] = doc
    return facts


def working_memory(documents: list[MemoryDocument], npc_ids: set[str]) -> list[MemoryDocument]:
    """Round-robin the present cast; stale versions remain available only as history."""
    by_npc: dict[str, list[MemoryDocument]] = defaultdict(list)
    current = sorted(
        latest_facts(documents).values(),
        key=lambda d: (_IMPORTANCE.get(d.significance or "", 0), d.created_at, d.id),
        reverse=True,
    )
    for doc in current:
        if doc.npc_id in npc_ids:
            by_npc[doc.npc_id].append(doc)
    groups = [by_npc[npc][:3] for npc in sorted(by_npc)]
    return [doc for group in zip_longest(*groups) for doc in group if doc is not None][:12]


def context_fallback(documents: list[MemoryDocument]) -> list[MemoryDocument]:
    """Keep a bounded projection of notes/chronicle if lexical recall finds nothing."""
    return [doc for doc in documents if doc.layer in {"session_note", "chronicle_summary"}]
