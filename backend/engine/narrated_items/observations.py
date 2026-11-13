"""Restrict current-placement observations without inventing an item taxonomy."""

from backend.engine.clothing.profiles import attachment_item_allowed, garment_for_item
from backend.engine.narrated_items.schema import ItemAction
from backend.engine.rule_engine import InventoryItem

_EFFECT_FIELDS = {
    name
    for name in InventoryItem.model_fields
    if name.startswith("stat_modifier_") or name in {"hp_change", "mana_change", "stamina_change"}
}


def validate_observation(action: ItemAction, item: dict, owner: str) -> None:
    """A current binding can repair custody only for an existing plain object."""
    if action.basis != "observed_placement":
        return
    if not attachment_item_allowed(item):
        raise ValueError("This item cannot be observed as a body attachment.")
    if owner == action.destination_owner:
        return
    if (
        str(item.get("item_type") or "").strip().upper() not in {"", "DEFAULT"}
        or garment_for_item(item) is not None
        or item.get("wearable_slots") not in (None, "", [])
        or any(item.get(field) not in (None, 0) for field in _EFFECT_FIELDS)
    ):
        raise ValueError(
            "A current observation cannot transfer this item's gameplay or garment ownership."
        )
