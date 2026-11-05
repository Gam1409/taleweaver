"""A small allowlist shared by model input and interpretation validation."""

from dataclasses import dataclass

from backend.engine.chpm import episodic_memory, host_observations
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


def build(mind: Mind, *, query: str = "") -> Window:
    available = [
        (entry.id, mind.sources[entry.event_id])
        for entry in mind.snapshot.evidence
        if entry.event_id in mind.sources
        and mind.sources[entry.event_id].kind in {"speech", "world_event"}
    ]
    selected = available[-6:]
    sources = {
        f"e{index}": (record_id, source, source.text[:1000])
        for index, (record_id, source) in enumerate(selected, 1)
    }
    recalled, recall_status = episodic_memory.recall(mind, available, query)
    sources.update(
        {
            f"r{index}": (item.record_id, item.source, item.fragment)
            for index, item in enumerate(recalled, 1)
        }
    )
    # These are visible excerpts, not permission to cite the omitted remainder.
    beliefs = {
        f"b{index}": belief
        for index, belief in enumerate(relationships.recent(mind.snapshot), 1)
        if belief.domain in relationships.DOMAINS
        and len(belief.statement) <= 240
        and belief.about_id != mind.genesis.scope.observer_id
    }
    facts = host_observations.previous(mind)
    subjects = tuple(
        sorted(
            (
                {s.speaker_id for _, s, _ in sources.values()}
                | {b.about_id for b in beliefs.values()}
                | set(facts.visible_actor_ids if facts else ())
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
                    "kind": "reported" if source.kind == "speech" else "witnessed",
                    "text": text,
                    "excerpted": len(text) < len(source.text),
                }
                for alias, (_, source, text) in sources.items()
            ],
            "existing_beliefs": claims,
            "evidence_omitted": len(available) - len(sources),
            "beliefs_omitted": len(mind.snapshot.beliefs) - len(beliefs),
            "episodic_recall": recall_status,
            "recollected_episodes": [
                {
                    "source_id": f"r{index}",
                    "episode_id": item.episode_id,
                    "detail": "fragment",
                    "historical": True,
                }
                for index, item in enumerate(recalled, 1)
            ],
        },
    )
