"""Turn-local host rejection reasons, independent of model-written narration."""

from collections.abc import Mapping
from typing import Any

from backend.engine import turn_controls
from backend.engine.npc_actions import control


def clear(manager: Any) -> None:
    manager._vn_item_rejection = None


def remember(
    manager: Any,
    error: ValueError | TypeError,
    *,
    intent: Any = None,
    owners: dict | None = None,
    captured: Mapping | None = None,
) -> str:
    if captured is None:
        return control.MESSAGES["preliminary_item_rejected"]
    if not turn_controls.bind_current(manager, captured, "preliminary_items"):
        raise control.CommandRejectedError("stale")
    operation = turn_controls.operation(captured, "item_proposal")
    control.trace_failure(operation, error, "preliminary_item_rejected")
    record = control.result(
        operation,
        "blocked",
        reason_code="preliminary_item_rejected",
        targets=sorted(_targets(intent, owners or {})) if intent is not None else [],
        diagnostic_error_type=type(error).__name__,
    )
    manager._vn_item_rejection = record
    return control.MESSAGES["preliminary_item_rejected"]


def _targets(intent: Any, owners: dict) -> set[str]:
    fields = ("new_inventory_items", "updated_inventory_items", "spawned_items")
    entries = [entry for field in fields for entry in getattr(intent, field, None) or []]
    ids = {getattr(entry, "id", None) for entry in entries}
    ids.update(getattr(intent, "removed_inventory_item_ids", None) or [])
    ids.update(getattr(intent, "deleted_entities", None) or [])
    actors = (
        {"__player__"}
        if any(
            getattr(intent, field, None)
            for field in (*fields, "removed_inventory_item_ids", "deleted_entities")
        )
        else set()
    )
    for update in getattr(intent, "updated_entities", None) or []:
        if update.inventory is None:
            continue
        actors.add(update.entity_id)
        ids.update(getattr(entry, "id", None) for entry in update.inventory)
    actors.update(owners[key] for key in ids if key in owners)
    ids.update(key for key, owner in owners.items() if owner in actors)
    return {value for value in ids | actors if isinstance(value, str) and value}


def current_rejection(manager: Any) -> dict | None:
    """Return only the canonical rejection bound to this saved player input."""
    rejected: dict | None = getattr(manager, "_vn_item_rejection", None)
    if (
        not rejected
        or not rejected.get("input_id")
        or not turn_controls.bind_current(manager, rejected, "preliminary_items")
    ):
        return None
    return rejected


def rejected_targets(manager: Any, rule_violations: list[str]) -> set[str] | None:
    """Only a current localized item denial can admit unrelated state extraction."""
    rejected = current_rejection(manager)
    if rule_violations or rejected is None:
        return None
    return set(rejected.get("targets") or ()) or None


def rejection_reason(manager: Any, rule_violations: list[str]) -> str:
    if rule_violations:
        text = "; ".join(rule_violations)
        excerpt = text if len(text) <= 600 else text[:600] + " [diagnostic excerpt]"
        return "The earlier rules check rejected the action: " + excerpt
    rejected = current_rejection(manager)
    if rejected is None:
        return ""
    return control.MESSAGES[rejected["reason_code"]]
