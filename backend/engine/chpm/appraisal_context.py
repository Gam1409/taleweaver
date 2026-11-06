"""A small allowlist shared by model input and interpretation validation."""

from dataclasses import dataclass

from backend.engine.chpm import agent_beliefs, belief_recall, episodic_memory, host_observations
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


def build(
    mind: Mind,
    *,
    query: str = "",
    recent_limit: int = 6,
    excerpt_chars: int = 1000,
    recall_limit: int = 3,
    belief_limit: int = 8,
    current_message_id: str | None = None,
    pinned: dict[str, tuple[str, Source, str]] | None = None,
    pinned_beliefs: dict[str, Belief] | None = None,
    focus_subjects: tuple[str, ...] = (),
) -> Window:
    focus = focus_subjects or belief_recall.subjects(mind, query, current_message_id, {})
    beliefs = {
        f"b{index}": belief
        for index, belief in enumerate(belief_recall.select(mind, belief_limit, query, focus), 1)
    }
    selected_beliefs = agent_beliefs.pinned_view(mind.snapshot.beliefs, pinned_beliefs or {})
    pinned_belief_ids = {belief.id for belief in selected_beliefs.values()}
    beliefs = {
        alias: belief for alias, belief in beliefs.items() if belief.id not in pinned_belief_ids
    }
    beliefs.update(selected_beliefs)
    grounding = belief_recall.grounds(mind, tuple(beliefs.values()), query, focus)
    available = [
        (entry.id, mind.sources[entry.event_id])
        for entry in mind.snapshot.evidence
        if entry.event_id in mind.sources
        and mind.sources[entry.event_id].kind in {"speech", "narration", "world_event"}
    ]
    current = [
        (key, source) for key, source in available if source.message_id == current_message_id
    ]
    older = [(key, source) for key, source in available if source.message_id != current_message_id]
    old_limit = max(0, recent_limit - len(current))
    selected = (older[-old_limit:] if old_limit else []) + current
    sources = {
        f"e{index}": (
            record_id,
            source,
            source.text[: 1000 if source.message_id == current_message_id else excerpt_chars],
        )
        for index, (record_id, source) in enumerate(selected, 1)
    }
    grounded_ids = set()
    by_record = {item[0]: alias for alias, item in sources.items()}
    for ground in grounding:
        alias = by_record.get(ground.record_id)
        if alias is None or ground.record_id in grounded_ids:
            continue
        grounded_ids.add(ground.record_id)
        key, source, text = sources[alias]
        if source.message_id != current_message_id and ground.fragment not in text:
            sources[alias] = (
                key,
                source,
                source.text if len(source.text) <= excerpt_chars else ground.fragment,
            )
    recalled, recall_status = episodic_memory.recall(mind, available, query)
    selected_ids = {key for key, _ in selected}
    historical: dict[str, tuple[str, Source, str]] = {}
    for ground in grounding:
        if (
            ground.record_id not in selected_ids
            and ground.record_id not in historical
            and len(historical) < recall_limit
        ):
            historical[ground.record_id] = (ground.record_id, ground.source, ground.fragment)
    lexical = [
        item
        for item in recalled
        if item.record_id not in selected_ids and item.record_id not in historical
    ]
    recalled = lexical[: max(0, recall_limit - len(historical))]
    recall_status["recalled_sources"] = len(recalled)
    recall_status["omitted_matches"] = max(0, recall_status["matched_sources"] - len(recalled))
    history = [
        *historical.values(),
        *((item.record_id, item.source, item.fragment) for item in recalled),
    ]
    sources.update({f"r{index}": item for index, item in enumerate(history, 1)})
    if pinned:
        pinned_ids = {item[0] for item in pinned.values()}
        sources = {alias: item for alias, item in sources.items() if item[0] not in pinned_ids}
        sources.update(pinned)
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
    order = {entry.id: index for index, entry in enumerate(mind.snapshot.evidence)}
    source_aliases = {item[0]: alias for alias, item in sources.items()}
    claims = relationships.claims(mind.snapshot, tuple(beliefs.values()))
    aliases = {belief.id: alias for alias, belief in beliefs.items()}
    basis: dict[str, dict[str, list[str]]] = {}
    visible_text = {item[0]: item[2] for item in sources.values()}
    for ground in grounding:
        if ground.fragment in visible_text.get(ground.record_id, ""):
            basis.setdefault(ground.record_id, {}).setdefault(aliases[ground.belief_id], []).append(
                ground.stance
            )
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
                    "kind": "reported" if source.reported else "witnessed",
                    **({"channel": "narration"} if source.kind == "narration" else {}),
                    "text": text,
                    "excerpted": len(text) < len(source.text),
                    "source_message_id": source.message_id,
                    "current_turn": source.message_id == current_message_id
                    if current_message_id is not None
                    else None,
                    "evidence_order": order[record_id],
                    **({"basis_for": basis[record_id]} if record_id in basis else {}),
                }
                for alias, (record_id, source, text) in sources.items()
            ],
            "existing_beliefs": claims,
            "evidence_omitted": len(
                {key for key, _ in available} - {item[0] for item in sources.values()}
            ),
            "beliefs_omitted": len(mind.snapshot.beliefs) - len(beliefs),
            "episodic_recall": recall_status,
            "recollected_episodes": [
                {
                    "source_id": source_aliases[item.record_id],
                    "episode_id": item.episode_id,
                    "detail": "fragment",
                    "historical": True,
                }
                for item in recalled
            ],
        },
    )
