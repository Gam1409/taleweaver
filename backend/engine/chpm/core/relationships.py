"""Qualitative, directed expectations; no inferred scalar trust or affect updates."""

from typing import Literal

from .contracts import Belief, Snapshot

Domain = Literal["reliability", "competence", "benevolence", "affection", "boundaries"]
DOMAINS = ("reliability", "competence", "benevolence", "affection", "boundaries")
POLICY = "local-beliefs-v1"


def recent(snapshot: Snapshot, limit: int = 8) -> tuple[Belief, ...]:
    """Order by accepted evidence, not arbitrary hash/lexicographical belief IDs."""
    order = {entry.id: index for index, entry in enumerate(snapshot.evidence)}
    ordered = sorted(
        snapshot.beliefs,
        key=lambda belief: max(order[ref] for ref in belief.interpretation_ids),
    )
    return tuple(ordered[-limit:]) if limit > 0 else ()


def claims(snapshot: Snapshot, beliefs: tuple[Belief, ...]) -> list[dict]:
    evidence = {entry.id: entry for entry in snapshot.evidence}
    result = []
    for belief in beliefs:
        if belief.domain not in DOMAINS:
            continue
        latest = evidence[belief.interpretation_ids[-1]]
        result.append(
            {
                "belief_id": belief.id,
                "about_id": belief.about_id,
                "domain": belief.domain,
                "statement": belief.statement,
                "status": belief.status,
                "probability": None,
                "alternatives": list(latest.alternatives),
                "unknowns": list(latest.unknowns),
            }
        )
    return result
