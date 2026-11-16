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
    return " ".join(filter(None, (continuity, _candidate_hint(candidate, choice, candidates))))


def _continuity_hint(choice: dict, no_previous_intention: bool) -> str:
    if no_previous_intention and (
        choice.get("continuity", "new") != "new" or choice.get("change_basis")
    ):
        return (
            "previous_intention is null: set choice.continuity='new' and choice.change_basis=[]. "
            "Keep your grounded preferred intention; current motives are not a change from a prior intention."
        )
    if (
        no_previous_intention
        or choice.get("continuity") != "maintain"
        or not choice.get("change_basis")
    ):
        return ""
    return (
        "choice.continuity='maintain' requires choice.change_basis=[]. Keep the grounded course; "
        "use 'revise' only for a real change supported by exact new evidence."
    )


def _candidate_hint(candidate: dict, choice: dict, candidates: dict) -> str:
    preferred, selected = choice.get("preferred"), choice.get("motive_ids")
    if not isinstance(preferred, str) or len(preferred) > 100:
        return ""
    return " ".join(
        filter(
            None,
            (
                _gate_hint(candidate, preferred),
                _motive_hint(preferred, selected, candidates.get(preferred)),
            ),
        )
    )


def _motive_hint(preferred: str, selected: object, body: object) -> str:
    if not _ids(selected):
        return ""
    motives = body.get("motives") if isinstance(body, dict) else None
    if not isinstance(motives, list) or not 1 <= len(motives) <= 3:
        return ""
    allowed = [entry.get("motive_id") for entry in motives if isinstance(entry, dict)]
    if not _ids(allowed) or len(allowed) != len(motives):
        return ""
    return problem(preferred, selected, allowed)


def _gate_hint(candidate: dict, preferred: str) -> str:
    if preferred != "CLARIFY" or candidate.get("question_gate") is not None:
        return ""
    return (
        "CLARIFY requires a valid decision-changing question_gate with two branches to other "
        "offered keys. Otherwise choose an independent offered intention and use its cited motive IDs."
    )


def _ids(value: object) -> TypeGuard[list[str]]:
    return (
        isinstance(value, list)
        and 1 <= len(value) <= 3
        and all(isinstance(key, str) and 1 <= len(key) <= 100 for key in value)
    )
