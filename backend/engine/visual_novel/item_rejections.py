"""Turn-local host rejection reasons, independent of model-written narration."""

from typing import Any

_HOST_REASONS = frozenset(
    {
        "Item identity is required.",
        "Unknown or unavailable item.",
        "Conflicting item destinations.",
        "Inventory owner is not present or accessible.",
        "Unknown inventory item.",
        "The player does not carry this item.",
        "Only existing available items can be consumed or removed.",
        "Removal needs a confirmed destination or consumption event.",
        "An item cannot be consumed and transferred in the same proposal.",
        "A player item cannot be removed and retained in the same proposal.",
    }
)


def clear(manager: Any) -> None:
    manager._vn_item_rejection = None


def remember(
    manager: Any, error: ValueError | TypeError, *, intent: Any = None, owners: dict | None = None
) -> str:
    reason = str(error)
    if reason not in _HOST_REASONS:
        reason = "The proposed item changes could not be validated against canonical possessions."
    manager._vn_item_rejection = {
        "message_id": getattr(manager, "_vn_player_message_id", None),
        "reason": reason,
        "targets": sorted(_targets(intent, owners or {})) if intent is not None else [],
    }
    return reason


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


def rejected_targets(manager: Any, rule_violations: list[str]) -> set[str] | None:
    """Only a current localized item denial can admit unrelated state extraction."""
    rejected = getattr(manager, "_vn_item_rejection", None)
    if (
        rule_violations
        or not rejected
        or rejected["message_id"] != getattr(manager, "_vn_player_message_id", None)
    ):
        return None
    return set(rejected.get("targets") or ()) or None


def rejection_reason(manager: Any, rule_violations: list[str]) -> str:
    if rule_violations:
        text = "; ".join(rule_violations)
        excerpt = text if len(text) <= 600 else text[:600] + " [diagnostic excerpt]"
        return "The earlier rules check rejected the action: " + excerpt
    rejected = getattr(manager, "_vn_item_rejection", None)
    if not rejected or rejected["message_id"] != getattr(manager, "_vn_player_message_id", None):
        return ""
    return f"The canonical item check rejected the proposed change: {rejected['reason']}"
