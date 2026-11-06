"""Bounded access to this observer's own propositions and their exact grounds."""

from typing import TYPE_CHECKING

from backend.engine.chpm.core import relationships
from backend.engine.chpm.core.contracts import Belief, Interpret
from backend.engine.chpm.core.history import events
from backend.engine.chpm.host_observations import previous
from backend.engine.chpm.host_state import Mind

if TYPE_CHECKING:
    from backend.engine.chpm.agent_tools import Tools

MAX_PINNED_BELIEFS = 2
MAX_SUBJECT_IDS = 32


def _readable(mind: Mind) -> list[Belief]:
    return [
        belief
        for belief in relationships.recent(mind.snapshot, len(mind.snapshot.beliefs))
        if belief.about_id != mind.genesis.scope.observer_id
        and belief.domain in relationships.DOMAINS
        and len(belief.statement) <= 240
    ]


def subject_view(mind: Mind) -> dict:
    subjects = list(dict.fromkeys(belief.about_id for belief in reversed(_readable(mind))))
    return {
        "player_actor_id": "@player",
        "belief_subject_ids": subjects[:MAX_SUBJECT_IDS],
        "omitted_belief_subjects": max(0, len(subjects) - MAX_SUBJECT_IDS),
    }


def _known(mind: Mind) -> set[str]:
    facts = previous(mind)
    return (
        {"@player"}
        | {belief.about_id for belief in mind.snapshot.beliefs}
        | {source.speaker_id for source in mind.sources.values()}
        | set(facts.visible_actor_ids if facts else ())
    )


def inspect(tools: "Tools", subject: str) -> dict:
    if subject == tools.mind.genesis.scope.observer_id or subject not in _known(tools.mind):
        return {"status": "unavailable_subject", "results": [], "omitted_beliefs": 0}
    matches = [belief for belief in _readable(tools.mind) if belief.about_id == subject]
    results = []
    for belief in reversed(matches[-MAX_PINNED_BELIEFS:]):
        alias = next(
            (key for key, value in tools.beliefs.items() if value == belief),
            f"ab{len(tools.beliefs) + 1}",
        )
        if alias not in tools.beliefs and len(tools.beliefs) >= MAX_PINNED_BELIEFS:
            break
        tools.beliefs[alias] = belief
        results.append(
            {
                "belief_id": alias,
                "about_id": belief.about_id,
                "domain": belief.domain,
                "statement": belief.statement,
                "status": belief.status,
                "subjective": True,
            }
        )
    return {
        "status": "ok",
        "results": results,
        "omitted_beliefs": len(matches) - len(results),
    }


def basis(tools: "Tools", alias: str) -> dict:
    belief = tools.beliefs.get(alias)
    if belief is None or belief not in tools.mind.snapshot.beliefs:
        return {"status": "unavailable_belief"}
    entries = [
        event.payload
        for event in events(tools.mind.snapshot)
        if isinstance(event.payload, Interpret)
        and event.payload.record_id in belief.interpretation_ids
    ]
    grounds = [_grounds(tools, entry) for entry in entries[-2:]]
    partial = any(citation["status"] != "ok" for row in grounds for citation in row["results"])
    return {
        "status": "partial" if partial else "ok",
        "belief_id": alias,
        "subjective": True,
        "status_of_belief": belief.status,
        "results": grounds,
        "omitted_interpretations": max(0, len(entries) - 2),
    }


def _grounds(tools: "Tools", entry: Interpret) -> dict:
    results = []
    for citation in entry.citations[:2]:
        source = tools.mind.sources.get(citation.record_id)
        if source is None or citation.quote not in source.text or len(citation.quote) > 300:
            results.append({"status": "unavailable_excerpt"})
            continue
        result = tools.expose(citation.record_id, source, fragment=citation.quote)
        results.append(result)
    return {
        "stance_toward_statement": entry.stance,
        "results": results,
        "omitted_citations": max(0, len(entry.citations) - 2),
    }


def pinned_view(mind_beliefs: tuple[Belief, ...], pinned: dict[str, Belief]) -> dict[str, Belief]:
    # Never make an old handle authoritative after a rewind or a revision.
    return {alias: belief for alias, belief in pinned.items() if belief in mind_beliefs}
