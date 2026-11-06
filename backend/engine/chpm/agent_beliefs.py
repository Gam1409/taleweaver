"""Bounded access to this observer's own propositions and their exact grounds."""

from typing import TYPE_CHECKING

from backend.engine.chpm.core import relationships
from backend.engine.chpm.core.contracts import Belief, Interpret
from backend.engine.chpm.core.history import events

if TYPE_CHECKING:
    from backend.engine.chpm.agent_tools import Tools

MAX_PINNED_BELIEFS = 2


def inspect(tools: "Tools", subject: str) -> dict:
    matches = [
        belief
        for belief in relationships.recent(tools.mind.snapshot, len(tools.mind.snapshot.beliefs))
        if belief.about_id == subject
        and subject != tools.mind.genesis.scope.observer_id
        and belief.domain in relationships.DOMAINS
        and len(belief.statement) <= 240
    ]
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
