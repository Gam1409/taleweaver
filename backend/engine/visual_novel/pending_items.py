"""Defer unregistered cosmetic acquisitions without treating missing IDs as denial."""

import json
from typing import Any

COSMETIC_TYPES = {"", "DEFAULT", "CLOTHING", "WEARABLE"}


def defer_unregistered_items(intent: Any, snapshot: Any) -> list[dict]:
    """Known/inaccessible IDs remain subject to normal ownership validation."""
    retained = []
    pending = []
    for item in intent.new_inventory_items or []:
        known = (
            item.id in snapshot.items
            or item.id in snapshot.catalog
            or any(
                str(row.get("name", "")).casefold() == item.name.casefold()
                for row in snapshot.catalog.values()
            )
        )
        cosmetic = str(item.item_type or "").upper() in COSMETIC_TYPES
        if not known and cosmetic:
            pending.append(
                {"name": item.name, "description": item.description, "item_type": item.item_type}
            )
        else:
            retained.append(item)
    intent.new_inventory_items = retained
    return pending


def pending_item_context(items: list[dict]) -> str:
    if not items:
        return ""
    return (
        "\nUNREGISTERED ORDINARY ITEM CANDIDATES (not yet possessions): "
        + json.dumps(items, ensure_ascii=False)
        + "\nMissing registration alone is not a failed action. Resolve the actual action under "
        "the established scene and character choices. Do not invent an available source or consent. "
        "Only an explicitly completed acquisition in the narration can register a new ordinary "
        "item afterwards. Requests, refusals and attempts remain uncompleted. Do not print this metadata."
    )
