"""Owner-only clothing sheet; NPC payloads must never reuse this projection."""

from typing import Any

from backend.engine.character_identity import identity_facts, identity_profile
from backend.engine.clothing.body_schema import BODY_SLOT_KEYS
from backend.engine.clothing.equipment_view import display_slots, layout
from backend.engine.clothing.profiles import garment_for_item, load_profile, owned_items
from backend.engine.clothing.projection import visible_character
from backend.engine.clothing.settings import clothing_settings


def player_clothing(avatar: Any, manifest: Any) -> dict | None:
    raw = identity_profile(avatar, getattr(avatar, "visual_profile", None))
    profile = load_profile(raw)
    if profile is None:
        return None
    detailed = clothing_settings(manifest)["detailed"]
    inventory = getattr(avatar, "inventory", None)
    equipment = getattr(avatar, "equipment", None)
    visible = visible_character(raw, inventory, detailed=detailed, equipment=equipment)
    if visible is None:
        return None
    visible_ids = {item["item_id"] for item in visible["clothing"]}
    items = owned_items(inventory, equipment=equipment)
    worn_ids = {item.item_id for item in profile.worn}
    for value in equipment.values() if isinstance(equipment, dict) else []:
        identifier = value.get("id") if isinstance(value, dict) else value
        if isinstance(identifier, str) and identifier in items:
            worn_ids.add(identifier)
    adult = profile.appearance.age_years is not None and profile.appearance.age_years >= 18
    rows = []
    attachments = []
    placement = {w.item_id: w for w in profile.worn}
    for identifier in sorted(worn_ids):
        item = items.get(identifier)
        garment = garment_for_item(item) if item else None
        worn = placement.get(identifier)
        if item and worn and worn.attachment_slot and adult:
            attachments.append(
                {
                    "id": identifier,
                    "name": str(item.get("name") or "")[:200],
                    "image_url": item.get("image_url"),
                    "slot": BODY_SLOT_KEYS[worn.attachment_slot],
                }
            )
            continue
        if item is None or garment is None or (garment.underwear and not (detailed and adult)):
            continue
        if not detailed and identifier not in visible_ids:
            continue
        rows.append(
            {
                "item_id": identifier,
                "name": str(item.get("name") or "")[:200],
                "description": garment.description if detailed else "",
                "layer": garment.layer,
                "visible": identifier in visible_ids,
                "underwear": garment.underwear,
                "image_url": item.get("image_url"),
                "slots": display_slots(item.get("wearable_slots"), list(garment.coverage)),
                "uncovered_regions": worn.uncovered_regions if worn else [],
            }
        )
    return {
        "appearance": {**profile.appearance.model_dump(), **identity_facts(avatar)},
        "worn": sorted(rows, key=lambda row: -row["layer"]),
        "detail_limited": visible["clothing_detail_limited"],
        "attachments": attachments,
        "layout": layout(
            raw,
            gender=identity_facts(avatar).get("gender"),
            npc_type="HUMANOID" if profile.body is None else None,
        ),
    }
