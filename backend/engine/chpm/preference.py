"""Qualitative personal-motive dominance; no invented utility or approval reward."""

from backend.engine.chpm.motivation_contracts import ResolvedMotive
from backend.engine.chpm.schema import ActionKind, Candidate

POLICY = "motive-frontier-v1"


def compare(
    candidates: list[Candidate], motives: dict[ActionKind, list[ResolvedMotive]]
) -> dict[ActionKind, list[ActionKind]]:
    features = {candidate.kind: _features(motives[candidate.kind]) for candidate in candidates}
    return {
        candidate.kind: sorted(
            other.kind
            for other in candidates
            if other.kind != candidate.kind
            and other.goal_alignment == candidate.goal_alignment
            and _dominates(features[other.kind], features[candidate.kind])
        )
        for candidate in candidates
    }


def _features(motives: list[ResolvedMotive]) -> tuple[set[tuple[str, str]], set[tuple[str, str]]]:
    # Exact content + canonical provenance avoids counting repeated aliases.
    # Reports, subjective beliefs and transient states are not extra votes.
    personal = [m for m in motives if m.source.status in {"authored", "declared"}]
    supports = {(m.source.provenance_id, m.source.text) for m in personal if m.effect == "supports"}
    tensions = {(m.source.provenance_id, m.source.text) for m in personal if m.effect == "tension"}
    return supports, tensions


def _dominates(
    better: tuple[set[tuple[str, str]], set[tuple[str, str]]],
    worse: tuple[set[tuple[str, str]], set[tuple[str, str]]],
) -> bool:
    supports, tensions = better
    old_supports, old_tensions = worse
    return (
        supports >= old_supports
        and tensions <= old_tensions
        and (supports != old_supports or tensions != old_tensions)
    )
