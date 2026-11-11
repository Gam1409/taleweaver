"""Track what the provider supplied before defaults erase missing-section evidence."""

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

ROOT_FIELDS = ("actions", "condition_updates", "scene_updates", "final_frame_actions")
STAGING_FIELDS = ("changes", "props", "explicit")


@dataclass(frozen=True)
class Sections:
    provided: frozenset[str]
    unconfirmed: tuple[str, ...]

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
        }

    def messages(self) -> list[str]:
        if not self.unconfirmed:
            return []
        return [
            "Some state checks need review: the response did not confirm sections "
            + ", ".join(self.unconfirmed)
            + ". Confirmed independent changes were retained."
        ]


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
