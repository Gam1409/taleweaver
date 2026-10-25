"""Owner-only clothing sheet; NPC payloads must never reuse this projection."""

from typing import Any

from backend.engine.clothing.profiles import garment_for_item, load_profile, owned_items
from backend.engine.clothing.projection import visible_character
from backend.engine.clothing.settings import clothing_settings


def player_clothing(avatar: Any, manifest: Any) -> dict | None:
    raw = getattr(avatar, "visual_profile", None)
    profile = load_profile(raw)
    if profile is None:
        return None
    detailed = clothing_settings(manifest)["detailed"]
    inventory = getattr(avatar, "inventory", None)
    equipment = getattr(avatar, "equipment", None)
    visible = visible_character(raw, inventory, detailed=detailed, equipment=equipment)
    visible_ids = {item["item_id"] for item in visible["clothing"]}
    items = owned_items(inventory, equipment=equipment)
    worn_ids = {item.item_id for item in profile.worn}
    for value in equipment.values() if isinstance(equipment, dict) else []:
        identifier = value.get("id") if isinstance(value, dict) else value
        if isinstance(identifier, str) and identifier in items:
            worn_ids.add(identifier)
    adult = profile.appearance.age_years is not None and profile.appearance.age_years >= 18
    rows = []
    for identifier in sorted(worn_ids):
        item = items.get(identifier)
        garment = garment_for_item(item) if item else None
        if garment is None or (garment.underwear and not (detailed and adult)):
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
            }
        )
    return {
        "appearance": profile.appearance.model_dump(),
        "worn": sorted(rows, key=lambda row: -row["layer"]),
        "detail_limited": visible["clothing_detail_limited"],
    }
