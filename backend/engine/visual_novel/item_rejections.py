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


def remember(manager: Any, error: ValueError | TypeError) -> str:
    reason = str(error)
    if reason not in _HOST_REASONS:
        reason = "The proposed item changes could not be validated against canonical possessions."
    manager._vn_item_rejection = {
        "message_id": getattr(manager, "_vn_player_message_id", None),
        "reason": reason,
    }
    return reason


def rejection_reason(manager: Any, rule_violations: list[str]) -> str:
    if rule_violations:
        text = "; ".join(rule_violations)
        excerpt = text if len(text) <= 600 else text[:600] + " [diagnostic excerpt]"
        return "The earlier rules check rejected the action: " + excerpt
    rejected = getattr(manager, "_vn_item_rejection", None)
    if not rejected or rejected["message_id"] != getattr(manager, "_vn_player_message_id", None):
        return ""
    return f"The canonical item check rejected the proposed change: {rejected['reason']}"
