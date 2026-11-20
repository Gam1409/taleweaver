"""Collect independently verifiable motive faults against the current observer catalogue."""

from __future__ import annotations

from typing import TYPE_CHECKING, get_args

from backend.engine.chpm.motivation_contracts import MotiveSource
from backend.engine.chpm.schema import ActionKind

if TYPE_CHECKING:
    from backend.engine.chpm.motivation import Catalogue


def _fault(path: tuple, kind: str, message: str) -> dict:
    return {"loc": path, "type": kind, "msg": message}


def _personal(source: MotiveSource, actor: str) -> bool:
    return source.subject_id == actor and source.status in {"authored", "declared"}


def _sources(kind: str, motives: list, catalogue: Catalogue) -> tuple[list, list, bool]:
    errors = []
    seen = set()
    resolved = []
    complete = True
    for index, motive in enumerate(motives):
        if not isinstance(motive, dict):
            complete = False
            continue
        identifier = motive.get("motive_id")
        if not isinstance(identifier, str) or not 1 <= len(identifier) <= 100:
            complete = False
            continue
        path = ("candidates", kind, "motives", index, "motive_id")
        if identifier in seen:
            errors.append(
                _fault(
                    path, "motive_duplicate", "Motive IDs repeat; cite distinct current sources."
                )
            )
        seen.add(identifier)
        source = catalogue.sources.get(identifier)
        if source is None:
            errors.append(
                _fault(
                    path,
                    "motive_unavailable",
                    "Motive source is unavailable; use a supplied motivation_context ID.",
                )
            )
        effect = motive.get("effect")
        if not isinstance(effect, str) or effect not in {"supports", "tension"}:
            complete = False
            continue
        if source is not None:
            resolved.append((source, effect))
    return errors, resolved, complete


def _candidate(kind: str, candidate: dict, catalogue: Catalogue, *, canonical: bool) -> list[dict]:
    motives = candidate.get("motives")
    if not isinstance(motives, list) or not 1 <= len(motives) <= 3:
        return []
    errors, resolved, complete = _sources(kind, motives, catalogue)
    if complete and not any(
        effect == "supports" and _personal(source, catalogue.observer_id)
        for source, effect in resolved
    ):
        errors.append(
            _fault(
                ("candidates", kind, "motives"),
                "motive_own_support",
                f"CHPM {kind} lacks a supporting character or active agenda motive. "
                "Cite genuine personal support or omit this alternative; do not relabel tension.",
            )
        )
    if canonical and complete and _goal_mismatch(candidate, resolved):
        errors.append(
            _fault(
                ("candidates", kind, "motives"),
                "motive_goal_alignment",
                f"CHPM {kind} goal alignment disagrees with its cited motive.",
            )
        )
    return errors


def _goal_mismatch(candidate: dict, resolved: list[tuple[MotiveSource, str]]) -> bool:
    alignment = candidate.get("goal_alignment")
    if alignment not in {"supports", "conflicts"}:
        return False
    quote = candidate.get("goal_quote")
    return not any(
        source.kind == "authored_goal"
        and isinstance(quote, str)
        and quote
        and quote in source.text
        and effect == ("supports" if alignment == "supports" else "tension")
        for source, effect in resolved
    )


def inspect(candidate: dict, catalogue: Catalogue, *, canonical: bool = False) -> list[dict]:
    """Schema faults stay with Pydantic; inspect only bounded, independently known fields."""
    candidates = candidate.get("candidates")
    if not isinstance(candidates, dict) or not 1 <= len(candidates) <= 4:
        return []
    errors = []
    for kind, value in candidates.items():
        if kind in get_args(ActionKind) and isinstance(value, dict):
            errors.extend(_candidate(kind, value, catalogue, canonical=canonical))
    return errors
