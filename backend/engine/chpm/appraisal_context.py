"""A small allowlist shared by model input and interpretation validation."""

from dataclasses import dataclass

from backend.engine.chpm.core import relationships
from backend.engine.chpm.core.contracts import Belief
from backend.engine.chpm.host_state import Mind, Source


@dataclass(frozen=True)
class Window:
    sources: dict[str, tuple[str, Source, str]]
    beliefs: dict[str, Belief]
    subjects: tuple[str, ...]
    payload: dict

    def identifiers(self) -> dict[str, list[str]]:
        return {
            "source_id": list(self.sources),
            "belief_id": list(self.beliefs),
            "about_id": list(self.subjects),
        }


def build(mind: Mind) -> Window:
    available = [
        (entry.id, mind.sources[entry.event_id])
        for entry in mind.snapshot.evidence
        if entry.event_id in mind.sources and mind.sources[entry.event_id].kind == "speech"
    ]
    selected = available[-6:]
    sources = {
        f"e{index}": (record_id, source, source.text[:1000])
        for index, (record_id, source) in enumerate(selected, 1)
    }
    # These are visible excerpts, not permission to cite the omitted remainder.
    beliefs = {
        f"b{index}": belief
        for index, belief in enumerate(relationships.recent(mind.snapshot), 1)
        if belief.domain in relationships.DOMAINS
        and len(belief.statement) <= 240
        and belief.about_id != mind.genesis.scope.observer_id
    }
    subjects = tuple(
        sorted(
            (
                {s.speaker_id for _, s, _ in sources.values()}
                | {b.about_id for b in beliefs.values()}
            )
            - {mind.genesis.scope.observer_id}
        )
    )
    claims = relationships.claims(mind.snapshot, tuple(beliefs.values()))
    aliases = {belief.id: alias for alias, belief in beliefs.items()}
    for claim in claims:
        claim["belief_id"] = aliases[claim["belief_id"]]
    return Window(
        sources,
        beliefs,
        subjects,
        {
            "policy": relationships.POLICY,
            "observer_id": mind.genesis.scope.observer_id,
            "known_subjects": list(subjects),
            "visible_evidence": [
                {
                    "source_id": alias,
                    "speaker_id": source.speaker_id,
                    "kind": "reported",
                    "text": text,
                    "excerpted": len(text) < len(source.text),
                }
                for alias, (_, source, text) in sources.items()
            ],
            "existing_beliefs": claims,
            "evidence_omitted": len(available) - len(selected),
            "beliefs_omitted": len(mind.snapshot.beliefs) - len(beliefs),
        },
    )
