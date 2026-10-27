"""Inventory mutations for validated rule events, preserving item identity semantics."""

from typing import TYPE_CHECKING

from backend.models.avatar import Avatar

if TYPE_CHECKING:
    from backend.engine.rule_engine import InventoryItem


def update_inventory_items(avatar: Avatar, updates: list["InventoryItem"]) -> None:
    """Merge non-null fields into the first inventory entry with the matching ID."""
    new_inv = list(avatar.inventory)
    modified = False
    for update in updates:
        if not update.id:
            continue
        for i, item in enumerate(new_inv):
            if item.get("id") == update.id:
                # Update fields
                update_dict = update.model_dump(exclude_none=True)
                new_inv[i] = {**item, **update_dict}
                modified = True
                break
    if modified:
        avatar.inventory = new_inv


def add_inventory_items(avatar: Avatar, items: list["InventoryItem"]) -> None:
    """Replace the first matching identified item, or append a newly acquired item."""
    # Reassign for SQLAlchemy state tracking; serialize Pydantic models to dicts
    new_inv = list(avatar.inventory)
    for item in items:
        item_dict = item.model_dump(exclude_none=True)

        # Check for existing ID to perform replacement/update
        found = False
        if item.id:
            for i, existing in enumerate(new_inv):
                if existing.get("id") == item.id:
                    new_inv[i] = item_dict
                    found = True
                    break

        if not found:
            new_inv.append(item_dict)

    avatar.inventory = new_inv
