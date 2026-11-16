"""Select observer-local propositions and their opposing grounds, not truth scores."""

import re
from dataclasses import dataclass

from backend.engine.chpm import passages
from backend.engine.chpm.core import relationships
from backend.engine.chpm.core.contracts import Belief, Interpret
from backend.engine.chpm.core.history import events
from backend.engine.chpm.host_state import Mind, Source


def words(text: str) -> set[str]:
    return {w for w in re.findall(r"[^\W_]+", text.casefold()) if len(w) >= 3}


def subjects(
    mind: Mind, query: str, message_id: str | None, names: dict[str, str]
) -> tuple[str, ...]:
    observer = mind.genesis.scope.observer_id
    explicit = [
        key
        for key, name in names.items()
        if key != observer
        and any(
            re.search(r"(?<!\w)" + re.escape(label) + r"(?!\w)", query, re.IGNORECASE)
            for label in (key, name)
            if label
        )
    ]
    speakers = [
        s.speaker_id
        for s in mind.sources.values()
        if s.message_id == message_id and s.kind == "speech" and s.speaker_id != observer
    ]
    return tuple(dict.fromkeys([*explicit, *speakers]))


def select(mind: Mind, limit: int, query: str, focus: tuple[str, ...]) -> tuple[Belief, ...]:
    available = [
        b
        for b in relationships.recent(mind.snapshot, len(mind.snapshot.beliefs))
        if b.domain in relationships.DOMAINS
        and len(b.statement) <= 240
        and b.about_id != mind.genesis.scope.observer_id
    ]
    order = {b.id: index for index, b in enumerate(available)}
    selected = _rank(mind, tuple(available), query, focus)[: max(0, limit)]
    # Keep stable chronological aliases after choosing by relevance.
    return tuple(sorted(selected, key=lambda b: order[b.id]))


@dataclass(frozen=True)
class Ground:
    record_id: str
    source: Source
    fragment: str
    belief_id: str
    stance: str


def grounds(
    mind: Mind, beliefs: tuple[Belief, ...], query: str = "", focus: tuple[str, ...] = ()
) -> list[Ground]:
    interpretations = {
        event.payload.record_id: event.payload
        for event in events(mind.snapshot)
        if isinstance(event.payload, Interpret)
    }
    found: list[Ground] = []
    # When only one historical slot fits, show the challenge rather than hide it.
    for belief in _rank(mind, beliefs, query, focus):
        found.extend(
            g
            for stance in ("challenge", "support")
            if (g := _ground(mind, interpretations, belief, stance)) is not None
        )
    return found


def _rank(
    mind: Mind, beliefs: tuple[Belief, ...], query: str, focus: tuple[str, ...]
) -> list[Belief]:
    cues = words(query)
    order = {entry.id: index for index, entry in enumerate(mind.snapshot.evidence)}
    evidence = {entry.id: entry for entry in mind.snapshot.evidence}
    return sorted(
        beliefs,
        key=lambda b: (
            len(focus) - focus.index(b.about_id) if b.about_id in focus else 0,
            len(
                cues
                & words(
                    b.statement
                    + " "
                    + b.domain
                    + " "
                    + " ".join(
                        citation.quote
                        for key in b.interpretation_ids[-2:]
                        for citation in evidence[key].citations
                    )
                )
            ),
            max(order[key] for key in b.interpretation_ids),
        ),
        reverse=True,
    )


def _ground(
    mind: Mind, interpretations: dict[str, Interpret], belief: Belief, stance: str
) -> Ground | None:
    matching = [
        interpretations[key]
        for key in reversed(belief.interpretation_ids)
        if key in interpretations and interpretations[key].stance == stance
    ]
    for entry in matching:
        valid = [
            c
            for c in entry.citations
            if c.record_id in mind.sources
            and c.quote in mind.sources[c.record_id].text
            and len(c.quote) <= 300
        ]
        if not valid:
            continue
        citation = valid[0]
        source = mind.sources[citation.record_id]
        # Whole short observations preserve negations around a cited phrase.
        fragment = _excerpt(source.text, citation.quote)
        return Ground(citation.record_id, source, fragment, belief.id, stance)
    return None


def _excerpt(text: str, quote: str) -> str:
    if len(text) <= 300:
        return text
    return next(
        (part for part in passages.index(text).values() if quote in part and len(part) <= 300),
        quote,
    )
