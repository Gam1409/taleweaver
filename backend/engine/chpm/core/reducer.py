"""Pure, deterministic, observer-local evidence transitions with no state patches."""

from .contracts import (
    Belief,
    Event,
    EventArchive,
    Evidence,
    Genesis,
    Interpret,
    Observe,
    Snapshot,
    Transition,
)
from .history import count, events
from .limits import MAX_EVENTS
from .log_layout import split


class TransitionError(ValueError):
    """Reject the whole transition; the caller retains the previous snapshot."""


def initial(genesis: Genesis) -> Snapshot:
    return Snapshot(genesis=genesis, sim_minute=genesis.sim_minute)


def apply(snapshot: Snapshot, event: Event, *, expected_revision: int) -> Transition:
    if event.scope != snapshot.genesis.scope:
        raise TransitionError("Event belongs to another world, branch or observer.")
    prior = next((item for item in events(snapshot) if item.event_id == event.event_id), None)
    if prior is not None:
        if prior != event:
            raise TransitionError("An event ID was reused with different content.")
        return Transition(snapshot=snapshot, duplicate=True)
    if snapshot.revision != expected_revision:
        raise TransitionError("Stale state revision.")
    if event.sequence <= snapshot.cursor or event.sim_minute < snapshot.sim_minute:
        raise TransitionError("Event cursor or simulation time moved backwards.")
    if count(snapshot) >= MAX_EVENTS:
        raise TransitionError("Journal capacity reached; no history was discarded.")
    evidence, beliefs, added = _project(snapshot, event)
    archived, journal = split((*snapshot.journal, event))
    result = Snapshot(
        genesis=snapshot.genesis,
        revision=snapshot.revision + 1,
        cursor=event.sequence,
        sim_minute=event.sim_minute,
        evidence=evidence,
        beliefs=beliefs,
        archive=(*snapshot.archive, *(EventArchive(events=block) for block in archived)),
        journal=journal,
    )
    return Transition(snapshot=result, added_roots=added)


def _project(
    snapshot: Snapshot, event: Event
) -> tuple[tuple[Evidence, ...], tuple[Belief, ...], tuple[str, ...]]:
    payload = event.payload
    if payload.kind == "advance":
        # No affect policy is installed yet. Time never heals trust or edits traits.
        return snapshot.evidence, snapshot.beliefs, ()
    if any(item.id == payload.record_id for item in snapshot.evidence):
        raise TransitionError("Evidence record ID already exists.")
    if isinstance(payload, Observe):
        item = Evidence(
            id=payload.record_id,
            text=payload.text,
            source_kind=payload.source_kind,
            root_ids=tuple(sorted(set(payload.root_ids))),
            event_id=event.event_id,
        )
        return (*snapshot.evidence, item), snapshot.beliefs, ()
    return _interpret(snapshot, event, payload)


def _interpret(
    snapshot: Snapshot, event: Event, payload: Interpret
) -> tuple[tuple[Evidence, ...], tuple[Belief, ...], tuple[str, ...]]:
    sources = {entry.id: entry for entry in snapshot.evidence}
    roots: set[str] = set()
    for citation in payload.citations:
        source = sources.get(citation.record_id)
        if source is None or citation.quote not in source.text:
            raise TransitionError("Citation is unavailable to this observer or is not exact.")
        roots.update(source.root_ids)
    old = next((entry for entry in snapshot.beliefs if entry.id == payload.belief_id), None)
    if old and (old.statement, old.about_id, old.domain) != (
        payload.statement,
        payload.about_id,
        payload.domain,
    ):
        raise TransitionError(
            "A belief ID cannot be reassigned to another proposition or relationship."
        )
    support = set(old.support_roots if old else ())
    challenge = set(old.challenge_roots if old else ())
    selected = support if payload.stance == "support" else challenge
    added = tuple(sorted(roots - support - challenge))
    selected.update(roots)
    belief = Belief(
        id=payload.belief_id,
        statement=payload.statement,
        about_id=payload.about_id,
        domain=payload.domain,
        revision=(old.revision if old else 0) + 1,
        interpretation_ids=(*(old.interpretation_ids if old else ()), payload.record_id),
        support_roots=tuple(sorted(support)),
        challenge_roots=tuple(sorted(challenge)),
        status="challenged" if challenge else "tentative",
    )
    record = Evidence(
        id=payload.record_id,
        text=payload.statement,
        source_kind=payload.source_kind,
        root_ids=tuple(sorted(roots)),
        citations=payload.citations,
        event_id=event.event_id,
        alternatives=payload.alternatives,
        unknowns=payload.unknowns,
    )
    beliefs = tuple(entry for entry in snapshot.beliefs if entry.id != belief.id) + (belief,)
    return (*snapshot.evidence, record), tuple(sorted(beliefs, key=lambda entry: entry.id)), added
