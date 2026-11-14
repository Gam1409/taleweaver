"""Track what the provider supplied before defaults erase missing-section evidence."""

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

ROOT_FIELDS = ("actions", "condition_updates", "scene_updates", "final_frame_actions", "movements")
STAGING_FIELDS = ("changes", "props", "explicit")


@dataclass(frozen=True)
class Sections:
    provided: frozenset[str]
    unconfirmed: tuple[str, ...]
    coverage: dict | None = None

    @property
    def needs_review(self) -> bool:
        return bool(
            self.unconfirmed
            or self.coverage
            and self.coverage.get("status") in {"incomplete", "needs_review"}
        )

    @property
    def scene_missing(self) -> tuple[str, ...]:
        return tuple(
            key for key in self.unconfirmed if key in {"scene_updates", "final_frame_actions"}
        )

    @property
    def staging_missing(self) -> frozenset[str]:
        return frozenset(
            key.removeprefix("staging.") for key in self.unconfirmed if key.startswith("staging.")
        )

    def details(self) -> dict:
        return {
            "response_sections": sorted(self.provided),
            "unconfirmed_sections": list(self.unconfirmed),
            **({"extraction_coverage": self.coverage} if self.coverage is not None else {}),
        }

    def messages(self) -> list[str]:
        messages = (
            [
                "Some state checks need review: the response did not confirm sections "
                + ", ".join(self.unconfirmed)
                + ". Confirmed independent changes were retained."
            ]
            if self.unconfirmed
            else []
        )
        if self.coverage and self.coverage.get("status") in {"incomplete", "needs_review"}:
            messages.append(_coverage_message(self.coverage))
        return messages


def _coverage_message(coverage: dict) -> str:
    budget = coverage.get("condition_budget") or {}
    deferred = budget.get("deferred_groups", [])
    if deferred:
        reason = f"State extraction reached its condition-update budget; {len(deferred)} source groups remain unapplied for review."
    elif budget.get("limit") and budget.get("proposed") == budget["limit"]:
        reason = "State extraction reached its condition-update budget. Some source groups were not fully accounted for."
    else:
        reason = "State extraction needs review: some source groups were not fully accounted for."
    return reason + " Confirmed independent changes were retained."


def read(result: Any, *, staging: bool) -> Sections:
    raw = result.model_dump(exclude_unset=True) if isinstance(result, BaseModel) else result
    raw = raw if isinstance(raw, dict) else {}
    expected = (*ROOT_FIELDS, "staging") if staging else ROOT_FIELDS
    missing = [key for key in expected if key not in raw]
    if staging and "staging" in raw:
        nested = raw["staging"]
        absent = missing_staging(nested) if isinstance(nested, dict) else frozenset()
        missing.extend(f"staging.{key}" for key in STAGING_FIELDS if key in absent)
        if not isinstance(nested, dict):
            missing.append("staging")
    return Sections(frozenset(raw) & frozenset(expected), tuple(missing))


def missing_staging(result: Any) -> frozenset[str]:
    """Standalone staging must preserve the same missing-versus-empty distinction."""
    raw = result.model_dump(exclude_unset=True) if isinstance(result, BaseModel) else result
    return frozenset(key for key in STAGING_FIELDS if not isinstance(raw, dict) or key not in raw)
