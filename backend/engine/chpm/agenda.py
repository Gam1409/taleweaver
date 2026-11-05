"""Source-bound declared goals and commitments, independent of transcript eviction."""

from typing import Any

from backend.engine.chpm import memory
from backend.engine.chpm.kernel import ChpmError, fingerprint
from backend.engine.chpm.schema import (
    AgendaClosure,
    AgendaEntry,
    AgendaIntent,
    Decision,
    Proposal,
    Verdict,
)

MAX_ACTIVE = 8
MAX_RECORDS = 256


async def recall(manager: Any, actor: str, entries: list[AgendaEntry]) -> list[AgendaEntry]:
    owned = [entry for entry in entries if entry.actor_id == actor]
    sources = [entry.source for entry in owned]
    sources.extend(entry.closure.source for entry in owned if entry.closure)
    valid = await memory.recall(manager, actor, sources, len(sources))
    result = []
    for entry in owned:
        if entry.source not in valid:
            continue
        retained = entry.model_copy(deep=True)
        if retained.closure and retained.closure.source not in valid:
            retained.closure = None
        result.append(retained)
    return result


def context(entries: list[AgendaEntry]) -> list[dict]:
    active = [entry for entry in entries if entry.closure is None]
    if len(active) > MAX_ACTIVE:
        raise ChpmError("CHPM has too many active agenda entries after source reconciliation.")
    return [
        {"id": entry.id, "kind": entry.kind, "text": entry.text, "quote": entry.source.quote}
        for entry in active
    ]


def validate_intent(intent: AgendaIntent | None, entries: list[AgendaEntry]) -> None:
    if intent is None:
        return
    active = [entry for entry in entries if entry.closure is None]
    if intent.entry_id:
        target = next((entry for entry in active if entry.id == intent.entry_id), None)
        if target is None or intent.text != target.text:
            raise ChpmError("CHPM agenda closure must identify an active owned entry exactly.")
        return
    if len(active) >= MAX_ACTIVE:
        raise ChpmError("CHPM active agenda is full; no new goal or commitment can be added.")
    if any(entry.text.casefold() == intent.text.casefold() for entry in active):
        raise ChpmError("CHPM agenda proposal duplicates an active entry.")


def validate_proposal(proposal: Proposal, entries: list[AgendaEntry]) -> None:
    for candidate in proposal.candidates:
        validate_intent(candidate.agenda_change, entries)
        if candidate.kind == "DEFER" and candidate.agenda_change:
            raise ChpmError("CHPM cannot change the agenda through a silent DEFER.")


def validate_evidence(decisions: dict[str, Decision], verdict: Verdict) -> None:
    expected = {actor for actor, item in decisions.items() if item.selected.agenda_change}
    ids = [entry.actor_id for entry in verdict.agenda_evidence]
    if set(ids) != expected or len(ids) != len(set(ids)):
        raise ChpmError("CHPM agenda review must cover exactly the selected changes.")
    speech = {entry.actor_id: entry.quote for entry in verdict.evidence}
    for entry in verdict.agenda_evidence:
        if (
            not entry.quote
            or len(entry.quote) > 600
            or entry.quote not in speech.get(entry.actor_id, "")
        ):
            raise ChpmError("CHPM agenda update needs exact evidence in the owner's own speech.")


def apply(
    entries: list[AgendaEntry], decisions: dict[str, Decision], verdict: Verdict, reply: Any
) -> list[AgendaEntry]:
    """Return a new ledger; never mutate quests, inventory, or inferred world facts."""
    if not verdict.matches:
        raise ChpmError("CHPM agenda cannot accept a rejected narration.")
    validate_evidence(decisions, verdict)
    result = [entry.model_copy(deep=True) for entry in entries]
    quotes = {entry.actor_id: entry.quote for entry in verdict.agenda_evidence}
    for actor, decision in decisions.items():
        intent = decision.selected.agenda_change
        if intent is None:
            continue
        _apply_one(result, actor, intent, quotes[actor], reply)
    return result


def _apply_one(
    entries: list[AgendaEntry], actor: str, intent: AgendaIntent, quote: str, reply: Any
) -> None:
    if reply.role != "assistant" or quote not in reply.content:
        raise ChpmError("CHPM agenda evidence does not match the saved narration.")
    source = memory.from_source(reply, actor, actor, quote, "own_speech")
    identifier = fingerprint(
        {"actor": actor, "source": source.model_dump(), "intent": intent.model_dump()}
    )
    if any(entry.id == identifier for entry in entries):
        return
    owned = [entry for entry in entries if entry.actor_id == actor]
    target = next((entry for entry in owned if entry.id == intent.entry_id), None)
    closure = (
        AgendaClosure(reason=intent.action, source=source)
        if intent.action in {"withdraw", "report_done"}
        else None
    )
    if target and target.text == intent.text and target.closure == closure:
        return
    validate_intent(intent, owned)
    if target:
        target.closure = closure
        return
    if len(entries) >= MAX_RECORDS:
        raise ChpmError("CHPM agenda archive is full. No records were discarded; turn not applied.")
    entries.append(
        AgendaEntry.model_validate(
            {
                "id": identifier,
                "actor_id": actor,
                "kind": intent.action,
                "text": intent.text,
                "source": source,
            }
        )
    )


def retract(entries: list[AgendaEntry], message_id: str) -> list[AgendaEntry]:
    result = []
    for entry in entries:
        if entry.source.source_message_id == message_id:
            continue
        retained = entry.model_copy(deep=True)
        if retained.closure and retained.closure.source.source_message_id == message_id:
            retained.closure = None
        result.append(retained)
    return result
