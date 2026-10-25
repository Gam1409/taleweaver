"""Project externally visible clothing by region, never raw hidden garment details."""

from typing import Any

from backend.engine.clothing.profiles import garment_for_item, load_profile, owned_items
from backend.engine.clothing.schema import REGIONS, Garment, VisualProfile, WornItem


def _worn_items(profile: VisualProfile, items: dict[str, dict], equipment: Any) -> list[WornItem]:
    worn = list(profile.worn)
    present = {value.item_id for value in worn}
    for raw in equipment.values() if isinstance(equipment, dict) else []:
        identifier = raw.get("id") if isinstance(raw, dict) else raw
        if not isinstance(identifier, str) or identifier in present or identifier not in items:
            continue
        if garment_for_item(items[identifier]) is None:
            continue
        worn.append(WornItem(item_id=identifier))
        present.add(identifier)
    return worn


def _covered(garment: Garment, worn: WornItem) -> set[str]:
    return set(garment.coverage) - set(worn.uncovered_regions)


def visible_character(
    raw_profile: Any,
    inventory: Any,
    *,
    detailed: bool = False,
    equipment: Any = None,
) -> dict | None:
    """Resolve higher opaque layers first; age/detail preferences never change coverage."""
    profile = load_profile(raw_profile)
    if profile is None:
        return None
    items = owned_items(inventory, equipment=equipment)
    worn = [w for w in _worn_items(profile, items, equipment) if w.item_id in items]
    garments = {w.item_id: garment_for_item(items[w.item_id]) for w in worn}
    result = {
        "appearance": profile.appearance.model_dump(),
        "clothing": [],
        "clothing_detail_limited": False,
    }
    # Unknown coverage cannot justify exposing the names of lower layers.
    if any(garments[w.item_id] is None for w in worn):
        result["clothing_detail_limited"] = True
        return result
    if any(not set(w.uncovered_regions).issubset(garments[w.item_id].coverage) for w in worn):
        result["clothing_detail_limited"] = True
        return result
    adult = profile.appearance.age_years is not None and profile.appearance.age_years >= 18
    for current in worn:
        garment = garments[current.item_id]
        covered = _covered(garment, current)
        blocked = set().union(
            *[
                _covered(garments[other.item_id], other)
                for other in worn
                if garments[other.item_id].opaque and garments[other.item_id].layer > garment.layer
            ]
        )
        visible = covered - blocked
        if not visible:
            continue
        if garment.underwear and not (detailed is True and adult):
            result["clothing_detail_limited"] = True
            continue
        item = items[current.item_id]
        name = item.get("name")
        result["clothing"].append(
            {
                "item_id": current.item_id,
                "name": name[:200] if isinstance(name, str) else "",
                "description": garment.description if detailed is True else "",
                "visible_regions": [region for region in REGIONS if region in visible],
            }
        )
    return result
