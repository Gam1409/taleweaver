"""Exact choice-ground diagnostics, including on structurally rejected proposals."""

import json
from collections.abc import Collection
from typing import TypeGuard

from backend.engine.chpm.kernel import ChpmError


def problem(preferred: str, selected: list[str], allowed: Collection[str]) -> str:
    duplicates = len(set(selected)) != len(selected)
    unavailable = sorted(set(selected) - set(allowed))
    if not duplicates and not unavailable:
        return ""
    details = [
        "Choice grounds must be distinct motives of the preferred candidate.",
        f"Preferred: {preferred}. Allowed motive IDs: {json.dumps(sorted(allowed))}.",
    ]
    if duplicates:
        details.append("Duplicate motive IDs must be removed.")
    if unavailable:
        details.append(f"Uncited motive IDs: {json.dumps(unavailable)}.")
    return " ".join(details)


def validate(preferred: str, selected: list[str], allowed: Collection[str]) -> None:
    reason = problem(preferred, selected, allowed)
    if reason:
        raise ChpmError(reason)


def repair_hint(candidate: dict | None, *, no_previous_intention: bool = False) -> str:
    """Inspect bounded IDs for feedback only; never validate or apply psychology."""
    if not isinstance(candidate, dict):
        return ""
    choice, candidates = candidate.get("choice"), candidate.get("candidates")
    if not isinstance(choice, dict) or not isinstance(candidates, dict):
        return ""
    continuity = _continuity_hint(choice, no_previous_intention)
    return " ".join(filter(None, (continuity, _motive_hint(choice, candidates))))


def _continuity_hint(choice: dict, no_previous_intention: bool) -> str:
    if not no_previous_intention or (
        choice.get("continuity", "new") == "new" and not choice.get("change_basis")
    ):
        return ""
    return (
        "previous_intention is null: set choice.continuity='new' and choice.change_basis=[]. "
        "Keep your grounded preferred intention; current motives are not a change from a prior intention."
    )


def _motive_hint(choice: dict, candidates: dict) -> str:
    preferred, selected = choice.get("preferred"), choice.get("motive_ids")
    if not isinstance(preferred, str) or len(preferred) > 100 or not _ids(selected):
        return ""
    body = candidates.get(preferred)
    motives = body.get("motives") if isinstance(body, dict) else None
    if not isinstance(motives, list) or not 1 <= len(motives) <= 3:
        return ""
    allowed = [entry.get("motive_id") for entry in motives if isinstance(entry, dict)]
    if not _ids(allowed) or len(allowed) != len(motives):
        return ""
    return problem(preferred, selected, allowed)


def _ids(value: object) -> TypeGuard[list[str]]:
    return (
        isinstance(value, list)
        and 1 <= len(value) <= 3
        and all(isinstance(key, str) and 1 <= len(key) <= 100 for key in value)
    )
