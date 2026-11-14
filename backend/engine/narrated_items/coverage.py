"""Cross-check fragment annotations against independent extraction sections."""

from copy import deepcopy
from dataclasses import dataclass, replace
from math import ceil
from typing import Any, Literal

from pydantic import BaseModel

from backend.engine.narrated_items.source_catalog import Catalog
from backend.engine.physical_conditions.schema import MAX_PROPOSALS

Tag = Literal[
    "items",
    "conditions",
    "scene",
    "staging",
    "unchanged",
    "historical",
    "uncertain",
    "conditions_deferred",
]
DOMAINS = {"items", "conditions", "scene", "staging"}
EXCLUSIVE = {"unchanged", "historical", "uncertain"}
FIELDS = {
    "actions": "items",
    "condition_updates": "conditions",
    "scene_updates": "scene",
    "final_frame_actions": "scene",
    "movements": "scene",
}
MAX_GROUPS = 24


def limits() -> dict[str, int]:
    return {"condition_updates": MAX_PROPOSALS}


def groups(catalog: Catalog) -> dict[str, list[str]]:
    references = catalog.references(minimum=1)
    size = max(1, ceil(len(references) / MAX_GROUPS))
    return {
        f"c{index // size}": references[index : index + size]
        for index in range(0, len(references), size)
    }


@dataclass(frozen=True)
class Audit:
    status: str
    issues: tuple[dict, ...] = ()
    blocked: int = 0
    condition_budget: dict | None = None

    def payload(self) -> dict:
        return {
            "status": self.status,
            "issues": list(self.issues),
            "blocked_candidates": self.blocked,
            **({"condition_budget": self.condition_budget} if self.condition_budget else {}),
        }


def inspect(result: Any, catalog: Catalog, *, staging: bool) -> tuple[Any, Audit]:
    body = result.model_dump() if isinstance(result, BaseModel) else deepcopy(result)
    if not isinstance(body, dict):
        return body, Audit("unavailable")
    updates = body.get("condition_updates")
    budget = {
        "limit": MAX_PROPOSALS,
        "proposed": len(updates) if isinstance(updates, list) else 0,
        "deferred_groups": [],
    }
    expected, raw = groups(catalog), body.pop("coverage", None)
    if not isinstance(raw, dict):
        return body, Audit("unavailable", condition_budget=budget)
    if set(raw) != set(expected):
        return body, Audit(
            "incomplete",
            (
                {
                    "reason": "missing_or_unknown_groups",
                    "missing": sorted(set(expected) - set(raw)),
                    "unknown": sorted(set(raw) - set(expected)),
                },
            ),
            condition_budget=budget,
        )
    allowed = DOMAINS if staging else DOMAINS - {"staging"}
    issues: list[dict] = []
    blocked = 0
    candidates = _candidates(body)
    for key, tags in raw.items():
        found, count = _group(
            key,
            tags,
            expected[key],
            candidates,
            catalog,
            allowed,
            capacity_reached=budget["proposed"] == MAX_PROPOSALS,
        )
        issues.extend(found)
        blocked += count
    budget["deferred_groups"] = [
        issue["group"] for issue in issues if issue["reason"] == "budget_deferred"
    ]
    return body, Audit("needs_review" if issues else "complete", tuple(issues), blocked, budget)


def annotate(result: Any, catalog: Catalog, sections: Any, *, staging: bool) -> tuple[Any, Any]:
    body, audit = inspect(result, catalog, staging=staging)
    return body, replace(sections, coverage=audit.payload())


def _group(
    key: str,
    tags: Any,
    references: list[str],
    candidates: list,
    catalog: Catalog,
    allowed: set[str],
    *,
    capacity_reached: bool,
) -> tuple[list[dict], int]:
    labels = (
        set(tags) if isinstance(tags, list) and all(isinstance(tag, str) for tag in tags) else set()
    )
    if (
        not labels
        or len(labels) != len(tags)
        or not labels <= allowed | EXCLUSIVE | {"conditions_deferred"}
        or (labels & EXCLUSIVE and len(labels) != 1)
    ):
        return [{"group": key, "reason": "invalid_tags"}], 0
    linked = [(domain, row) for domain, row in candidates if _linked(row, references, catalog)]
    missing = labels & DOMAINS - {domain for domain, _ in linked}
    issues: list[dict] = (
        [{"group": key, "reason": "missing_proposals", "domains": sorted(missing)}]
        if missing
        else []
    )
    if "conditions_deferred" in labels:
        issues.append(
            {
                "group": key,
                "reason": "budget_deferred" if capacity_reached else "unjustified_budget_deferral",
                "domains": ["conditions"],
            }
        )
    if labels == {"uncertain"}:
        issues.append({"group": key, "reason": "uncertain_interpretation"})
    blocked = 0
    if labels & {"historical", "uncertain"}:
        for _, row in linked:
            row["evidence"] = None
            blocked += 1
        if linked:
            issues.append(
                {"group": key, "reason": "non_current_candidate", "candidates": len(linked)}
            )
    return issues, blocked


def _candidates(body: dict) -> list[tuple[str, dict]]:
    rows = [(domain, row) for field, domain in FIELDS.items() for row in _rows(body.get(field))]
    staging = body.get("staging")
    if isinstance(staging, dict):
        rows.extend(
            ("staging", row)
            for field in ("changes", "props", "explicit")
            for row in _rows(staging.get(field))
        )
    return rows


def _linked(row: dict, references: list[str], catalog: Catalog) -> bool:
    evidence = row.get("evidence")
    if not isinstance(evidence, str):
        return False
    try:
        chosen = (
            catalog.resolve(evidence, allow_room=True)
            if evidence.startswith(("narration:", "room:", "passage:"))
            else catalog.literal(evidence, allow_room=True)
        )
    except ValueError:
        return False
    if chosen.kind != "narration":
        return False
    return any(
        catalog.resolve(reference, allow_room=False).span.start <= chosen.span.start
        and chosen.span.end <= catalog.resolve(reference, allow_room=False).span.end
        for reference in references
    )


def _rows(value: Any) -> list[dict]:
    return [row for row in value if isinstance(row, dict)] if isinstance(value, list) else []
