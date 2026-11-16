"""Fit a correction's complete wire without dropping authoritative proof or target state."""

import json
from dataclasses import dataclass
from typing import Any, cast

from backend.engine.narrated_items.extraction_repair import Additions

# Additions cannot change these domains. Their canonical checks still run on the
# retained original extraction; current item/condition state and blocked scopes stay.
UNRELATED_DOMAINS = frozenset({"scene_staging", "scene_continuity", "movement_context"})


@dataclass(frozen=True)
class Policy:
    items: str
    conditions: str
    shared: str = ""

    def instructions(self, domains: set[str]) -> str:
        return self.shared + "".join(getattr(self, domain) for domain in sorted(domains))


@dataclass(frozen=True)
class Prepared:
    instructions: str
    content: str
    input_chars: int
    focused: bool


def prepare(
    llm: Any,
    instructions: str,
    context: dict,
    schema: dict,
    limit: int,
    *,
    focused_instructions: str | None = None,
) -> Prepared | None:
    for focused in (False, True):
        selected = _focused(context) if focused else context
        system = (
            focused_instructions if focused and focused_instructions is not None else instructions
        )
        content = json.dumps(selected, ensure_ascii=False, separators=(",", ":"))
        size = _size(llm, system, content, schema)
        if size <= limit:
            return Prepared(system, content, size, focused)
    return None


def _focused(context: dict) -> dict:
    selected = {key: value for key, value in context.items() if key not in UNRELATED_DOMAINS}
    # Preserve current public identities and ownership even when large descriptive
    # scene ledgers and historical poses are outside the correction's domain.
    for name, fields in (
        ("scene_continuity", ("scene_id", "public_subjects")),
        ("scene_staging", ("scene_id", "owned_items")),
    ):
        source = context.get(name)
        if isinstance(source, dict):
            selected[name] = {key: source[key] for key in fields if key in source}
    correction = context.get("coverage_correction")
    if isinstance(correction, dict):
        selected["coverage_correction"] = _focused_feedback(correction)
        groups = context.get("extraction_coverage_groups")
        missing = correction.get("missing_proposals", {})
        if isinstance(groups, dict) and isinstance(missing, dict):
            selected["extraction_coverage_groups"] = {
                key: value for key, value in groups.items() if key in missing
            }
    return selected


def _focused_feedback(correction: dict) -> dict:
    previous = correction.get("previous_extraction")
    if not isinstance(previous, dict):
        return correction
    # Missing classifications are already listed explicitly. Keep every prior
    # action/condition candidate; the host retains and validates all classifications.
    return {
        **correction,
        "previous_extraction": {key: value for key, value in previous.items() if key != "coverage"},
    }


def _size(llm: Any, instructions: str, content: str, schema: dict) -> int:
    measure = getattr(llm, "structured_input_characters", None)
    if callable(measure):
        return cast(
            int, measure(instructions, content, Additions, llm.model, response_schema=schema)
        )
    # Narrow model ports have no provider-specific wire builder. Dispatch still
    # enforces its explicit budget; include the entire prompt/schema conservatively.
    return len(instructions) + len(content) + len(json.dumps(schema, ensure_ascii=False))
