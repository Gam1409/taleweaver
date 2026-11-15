"""Conservative additions for explicitly reported extraction omissions."""

from copy import deepcopy
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from backend.engine.narrated_items import coverage, reference_schema, response_sections
from backend.engine.narrated_items.schema import (
    ExistingItemAction,
    ItemExtraction,
    NewItemAction,
    SharedItemExtraction,
)
from backend.engine.narrated_items.source_catalog import Catalog
from backend.engine.physical_conditions.schema import MAX_PROPOSALS, ConditionProposal

ACTION_LIMIT = ItemExtraction.model_json_schema()["properties"]["actions"]["maxItems"]


class ClassificationReview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    group: str = Field(min_length=2, max_length=4)
    domain: Literal["items", "conditions"]
    reason: Literal["no_supported_change", "different_domain", "repeated_confirmation", "uncertain"]


class Additions(BaseModel):
    """The model cannot replace prior candidates, coverage, or independent sections."""

    model_config = ConfigDict(extra="forbid")
    actions: list[ExistingItemAction | NewItemAction] = Field(
        default_factory=list, max_length=ACTION_LIMIT
    )
    condition_updates: list[ConditionProposal] = Field(
        default_factory=list, max_length=MAX_PROPOSALS
    )
    classification_review: list[ClassificationReview] = Field(
        default_factory=list,
        max_length=coverage.MAX_GROUPS * 2,
        description=(
            "Only unresolved missing group/domain pairs, never a pair supported by an added "
            "proposal. Adding a proposal and reviewing its same group/domain are mutually "
            "exclusive. Return [] when all missing pairs have supported additions."
        ),
    )


def schema(catalog: Catalog, *, domains: set[str] | None = None) -> dict:
    result = reference_schema.citation_schema(Additions, catalog)
    result["required"] = list(result["properties"])
    if domains is not None:
        for domain, field in (("items", "actions"), ("conditions", "condition_updates")):
            if domain not in domains:
                result["properties"][field] = {
                    "type": "array",
                    "items": {"type": "null"},
                    "maxItems": 0,
                    "default": [],
                }
        result["$defs"]["ClassificationReview"]["properties"]["domain"]["enum"] = sorted(domains)
        _prune_unused_definitions(result)
    return result


def _prune_unused_definitions(schema: dict) -> None:
    definitions = schema.get("$defs", {})
    pending: list = [{key: value for key, value in schema.items() if key != "$defs"}]
    retained = set()
    while pending:
        node = pending.pop()
        if isinstance(node, list):
            pending.extend(node)
            continue
        if not isinstance(node, dict):
            continue
        ref = node.get("$ref", "")
        name = ref.removeprefix("#/$defs/") if isinstance(ref, str) else ""
        if name in definitions and name not in retained:
            retained.add(name)
            pending.append(definitions[name])
        pending.extend(value for key, value in node.items() if key != "$defs")
    schema["$defs"] = {name: value for name, value in definitions.items() if name in retained}


def targets(result: ItemExtraction, catalog: Catalog, *, staging: bool) -> dict[str, set[str]]:
    """Only a complete, unambiguous classification with missing rows admits repair."""
    sections = response_sections.read(result, staging=staging)
    _, audit = coverage.inspect(result, catalog, staging=staging)
    if sections.unconfirmed or not audit.issues:
        return {}
    if any(
        issue["reason"] != "missing_proposals"
        or not set(issue["domains"]) <= {"items", "conditions"}
        for issue in audit.issues
    ):
        return {}
    missing = {issue["group"]: set(issue["domains"]) for issue in audit.issues}
    capacities = {
        "items": ACTION_LIMIT - len(result.actions),
        "conditions": MAX_PROPOSALS - len(result.condition_updates),
    }
    if any(capacities[domain] <= 0 for domains in missing.values() for domain in domains):
        return {}
    return missing


def merge(
    original: SharedItemExtraction,
    additions: Additions,
    missing: dict[str, set[str]],
    catalog: Catalog,
    *,
    staging: bool,
) -> tuple[SharedItemExtraction, dict]:
    """Retain original effects and labels; notes never discharge a changed domain."""
    raw = additions.model_dump(mode="json")
    notes = raw.pop("classification_review")
    permitted = {key: set(domains) for key, domains in missing.items()}
    for note in notes:
        permitted.get(note["group"], set()).discard(note["domain"])
    if not _notes_match(notes, missing) or not _valid_additions(original, raw, permitted, catalog):
        return original, {"status": "invalid_additions"}
    if not any(raw.values()):
        return original, {
            "status": "classification_review" if notes else "unresolved",
            "classification_review": notes,
        }
    body = original.model_dump(exclude_unset=True)
    for field, values in raw.items():
        body[field] = [*body.get(field, []), *values]
    try:
        merged = SharedItemExtraction.model_validate(body)
    except ValidationError:
        return original, {"status": "invalid_additions"}
    _, audit = coverage.inspect(merged, catalog, staging=staging)
    return merged, {
        "status": "repaired" if audit.status == "complete" else "unresolved",
        "added": {field: len(values) for field, values in raw.items()},
        "classification_review": notes,
    }


def _notes_match(notes: list[dict], missing: dict[str, set[str]]) -> bool:
    return all(note["domain"] in missing.get(note["group"], ()) for note in notes)


def _valid_additions(
    original: SharedItemExtraction,
    raw: dict[str, list],
    missing: dict[str, set[str]],
    catalog: Catalog,
) -> bool:
    limits = {"actions": ACTION_LIMIT, "condition_updates": MAX_PROPOSALS}
    domains = {"actions": "items", "condition_updates": "conditions"}
    original_body = original.model_dump()
    groups = coverage.groups(catalog)
    for field, rows in raw.items():
        previous = original_body[field]
        if len(previous) + len(rows) > limits[field] or _overwrites(field, previous, rows):
            return False
        allowed = [groups[key] for key, domains_ in missing.items() if domains[field] in domains_]
        if any(not coverage.anchored(row, allowed, catalog) for row in rows):
            return False
    return True


def _overwrites(field: str, previous: list, rows: list) -> bool:
    identity = "item_id" if field == "actions" else "condition_id"
    occupied = {row.get(identity) for row in previous if isinstance(row, dict)} - {None}
    # An existing lifecycle chain is not extended out of order by an appended patch.
    return any(row.get(identity) in occupied for row in rows)


def feedback(result: SharedItemExtraction, missing: dict[str, set[str]]) -> dict:
    return {
        "previous_extraction": deepcopy(
            result.model_dump(
                include={"coverage", "actions", "condition_updates"}, exclude_unset=True
            )
        ),
        "missing_proposals": {key: sorted(value) for key, value in missing.items()},
        "remaining_capacity": {
            "actions": max(0, ACTION_LIMIT - len(result.actions)),
            "condition_updates": max(0, MAX_PROPOSALS - len(result.condition_updates)),
        },
    }


INSTRUCTIONS = """
The previous completed extraction classified source groups as changed but supplied
no corresponding anchored proposal. Return only ADDITIONAL actions/condition_updates
for the listed missing group/domain, within remaining_capacity. Preserve original
IDs and do not repeat, replace, reverse, or extend an existing proposal's lifecycle.
For EACH missing (group, domain) pair, choose exactly one outcome: supported additions
OR a classification_review note, never both for that same pair. A review note is not
rationale or a success annotation for a supplied proposal. If you add an action for
c0/items, do not also review c0/items as no_supported_change, different_domain,
repeated_confirmation or uncertain. Notes for OTHER unresolved pairs may coexist
with additions. Return classification_review=[] when all missing pairs are supplied.
All prior instructions, source restrictions and domain ownership rules still apply.
Do not invent a transfer, wear observation, body fact or parallel property merely to
make coverage complete. Cleaning, contents or condition changes do not by themselves
establish an ownership/wear action. A later repeated confirmation is not a new change.
The original classifications cannot be withdrawn by this patch. If a tag instead
appears wrong, a change is unsupported, or interpretation remains uncertain, return
no forced proposal; report its group/domain in classification_review for manual
review. Those notes are untrusted classifications, not proof that a change occurred
or permission to mark it handled. Do not return scene/staging updates or coverage.
Only one correction attempt is available; unchanged original effects are retained.
"""
