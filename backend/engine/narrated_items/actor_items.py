"""Working-copy possession and wear mutations shared by narration and commands."""

from copy import deepcopy
from typing import Any

from backend.engine.clothing.equipment_view import display_slots
from backend.engine.clothing.profiles import (
    load_profile,
    owned_items,
    placement_profile,
    potentially_wearable,
    validate_profile,
    without_item,
)
from backend.engine.clothing.schema import WornItem
from backend.engine.item_logic import normalize_equipment_keys
from backend.engine.narrated_items.wear import validate_wear
from backend.engine.visual_novel.continuity import PLAYER


def _id(item: Any) -> Any:
    return item.get("id") if isinstance(item, dict) else item


def remove(actor: dict, item_id: str) -> None:
    """Custody loss removes only this item's worn and unassessed references."""
    raw = actor.get("visual_profile")
    if raw and load_profile(raw) is None:
        raise ValueError("Invalid appearance profile; item transfer requires review.")
    actor["inventory"] = [item for item in actor["inventory"] if _id(item) != item_id]
    actor["resolved_inventory"] = [
        item for item in actor["resolved_inventory"] if _id(item) != item_id
    ]
    actor["equipment"] = {
        slot: None if _id(item) == item_id else item for slot, item in actor["equipment"].items()
    }
    if not raw:
        return
    actor["visual_profile"] = without_item(raw, item_id)


def _equip_worn(actor: dict, item: dict, preferred_slot: str | None) -> None:
    supplied = item.get("wearable_slots") or []
    supplied = [supplied] if isinstance(supplied, str) else supplied
    slots = [slot for raw in supplied for slot in display_slots([raw], [])]
    preferred = display_slots(preferred_slot, [])
    if preferred and preferred[0] in slots:
        slots.insert(0, preferred[0])
    equipment = normalize_equipment_keys(actor["equipment"])
    slot = next((slot for slot in slots if not equipment.get(slot)), None)
    if slot is None:
        return
    actor["equipment"][slot] = deepcopy(item)
    actor["inventory"] = [row for row in actor["inventory"] if _id(row) != item["id"]]


def receive(
    actor: dict,
    item: dict,
    disposition: str,
    detailed: bool,
    worn: WornItem | None = None,
    preferred_slot: str | None = None,
) -> None:
    """Retain a positive placement while leaving unrelated old garments unassessed."""
    identifier = item["id"]
    raw = actor.get("visual_profile")
    profile = None
    if disposition == "worn" or potentially_wearable(item):
        # Capacity/unsupported-profile failure must precede inventory replacement.
        profile = placement_profile(
            raw, actor["resolved_inventory"], identifier, equipment=actor["equipment"]
        )
        if not raw:
            profile.appearance.age_years = actor.get("age_years")
    if disposition == "worn" and (profile is None or worn is None):
        raise ValueError("Wearing requires valid garment metadata and a confirmed placement.")
    owned = owned_items(actor["inventory"], equipment=actor["equipment"])
    if identifier not in owned or not any(_id(row) == identifier for row in actor["inventory"]):
        actor["inventory"].append(deepcopy(item))
    actor["resolved_inventory"] = [
        row for row in actor["resolved_inventory"] if _id(row) != identifier
    ] + [deepcopy(item)]
    if disposition == "worn" and profile is not None and worn is not None:
        validate_wear(actor, item, profile, worn, detailed)
        if identifier not in {entry.item_id for entry in profile.worn}:
            profile.worn.append(worn)
    if profile is not None:
        actor["visual_profile"] = validate_profile(
            profile, actor["resolved_inventory"], equipment=actor["equipment"]
        ).model_dump()
    if (
        disposition == "worn"
        and actor["id"] == PLAYER
        and worn is not None
        and worn.attachment_slot is None
    ):
        # Receiving clothes never equips a weapon or replaces another worn layer.
        _equip_worn(actor, item, preferred_slot)
