"""Qualify reviewed movement transcripts with receipts from their authoritative owner."""

from typing import Any

from backend.core.text_passages import spans
from backend.engine.chpm.kernel import digest
from backend.engine.chpm.memory_contracts import MemoryEntry
from backend.engine.narrated_movement.outcomes import MovementOutcome, for_quote


def read(state: Any, reply: Any) -> tuple[MovementOutcome, ...]:
    from backend.engine.narrated_items.runtime import KEY

    ledger = (state.entity_states or {}).get(KEY)
    audit = ledger.get("movement_check") if isinstance(ledger, dict) else None
    if not isinstance(audit, dict) or (
        audit.get("message_id"),
        audit.get("revision_id"),
        audit.get("content_hash"),
    ) != (reply.id, reply.revision_id, digest(reply.content)):
        return ()
    rows = audit.get("outcomes", [])
    if not isinstance(rows, list) or len(rows) > 8:
        return ()
    try:
        entries = tuple(MovementOutcome.model_validate(row) for row in rows)
    except ValueError:
        return ()
    return tuple(
        entry for entry in entries if entry.evidence_span.matches(reply.content, entry.evidence)
    )


def qualify(
    entries: tuple[MovementOutcome, ...], reply: Any, memories: list[MemoryEntry]
) -> list[MemoryEntry]:
    return [
        memory.model_copy(
            update={
                "movement_outcomes": for_quote(
                    entries, reply.content, memory.quote, memory.observer_id, memory.action_span
                )
            }
        )
        if memory.kind == "own_action"
        else memory
        for memory in memories
    ]


def conflicts(
    entries: tuple[MovementOutcome, ...], actor_ids: set[str], start: int, end: int
) -> bool:
    return any(
        entry.status != "applied"
        and entry.actor_id in actor_ids
        and start < entry.evidence_span.end
        and entry.evidence_span.start < end
        for entry in entries
    )


def check_causal(update: Any, entries: tuple[MovementOutcome, ...], text: str) -> None:
    available = spans(text)
    actors = {entry.actor_id for entry in entries}
    for fact in update.facts.values():
        passage = available.get(fact.passage_id)
        if passage and conflicts(entries, actors, passage.start, passage.end):
            raise ValueError("Causal evidence contains a blocked or unconfirmed movement.")
