"""Project externally visible clothing by region, never raw hidden garment details."""

from typing import Any, Literal

from backend.engine.clothing.profiles import (
    attachment_item_allowed,
    equipped_garment_ids,
    garment_for_item,
    load_profile,
    owned_items,
)
from backend.engine.clothing.schema import REGIONS, Garment, Region, VisualProfile, WornItem


def _worn_items(profile: VisualProfile, items: dict[str, dict], equipment: Any) -> list[WornItem]:
    worn = [item for item in profile.worn if item.attachment_slot is None]
    present = {value.item_id for value in profile.worn}
    for raw in equipment.values() if isinstance(equipment, dict) else []:
        identifier = raw.get("id") if isinstance(raw, dict) else raw
        if not isinstance(identifier, str) or identifier in present or identifier not in items:
            continue
        if garment_for_item(items[identifier]) is None:
            continue
        worn.append(WornItem(item_id=identifier))
        present.add(identifier)
    return worn


def _covered(garment: Garment, worn: WornItem) -> set[Region]:
    return set(garment.coverage) - set(worn.uncovered_regions)


def known_worn_item_ids(
    raw_profile: Any, inventory: Any, *, equipment: Any = None
) -> set[str] | None:
    """Known wear IDs include legacy equipped garments, independently of occlusion."""
    profile = load_profile(raw_profile)
    items = owned_items(inventory, equipment=equipment)
    if (
        profile is None
        or not profile.wear_assessment_complete
        or any(row.item_id not in items for row in profile.worn)
        or set(profile.unassessed_wear_item_ids) & items.keys()
    ):
        return None
    return {row.item_id for row in profile.worn} | {
        row.item_id for row in _worn_items(profile, items, equipment)
    }


def item_wear_state(
    raw_profile: Any, inventory: Any, item_id: str, *, equipment: Any = None
) -> Literal["worn", "carried", "unknown"]:
    """Read one owned placement without treating unrelated missing facts as absence."""
    items = owned_items(inventory, equipment=equipment)
    if item_id not in items:
        return "unknown"
    profile = load_profile(raw_profile)
    if item_id in equipped_garment_ids(items, equipment) or (
        profile is not None and any(row.item_id == item_id for row in profile.worn)
    ):
        return "worn"
    if (
        profile is None
        or item_id in profile.unassessed_wear_item_ids
        or any(row.item_id not in items for row in profile.worn)
    ):
        return "unknown"
    return "carried"


def _unassessed(profile: VisualProfile, items: dict[str, dict]) -> list[Garment | None]:
    return [
        garment_for_item(items[key]) for key in profile.unassessed_wear_item_ids if key in items
    ]


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
    candidates = {w.item_id: garment_for_item(items[w.item_id]) for w in worn}
    possible = _unassessed(profile, items)
    result: dict[str, Any] = {
        "appearance": profile.appearance.model_dump(),
        "clothing": [],
        "clothing_detail_limited": bool(possible),
    }
    # One observed placement cannot establish the absence of unstructured outer layers.
    if not profile.wear_assessment_complete:
        result["clothing_detail_limited"] = True
        return result
    # Unknown coverage cannot justify exposing the names of lower layers.
    if (
        any(garment is None for garment in possible)
        or any(candidates[w.item_id] is None for w in worn)
        or any(
            row.attachment_slot
            and row.item_id in items
            and not attachment_item_allowed(items[row.item_id])
            for row in profile.worn
        )
    ):
        result["clothing_detail_limited"] = True
        return result
    garments = {key: value for key, value in candidates.items() if value is not None}
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
                if garments[other.item_id].opaque
                and garments[other.item_id].category != "accessory"
                and garments[other.item_id].layer > garment.layer
            ]
        )
        blocked.update(
            region
            for candidate in possible
            if candidate is not None
            and candidate.opaque
            and candidate.category != "accessory"
            and candidate.layer >= garment.layer
            for region in candidate.coverage
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
                **({"partially_removed": True} if current.partially_removed else {}),
                "visible_regions": [region for region in REGIONS if region in visible],
                **(
                    {"uncovered_regions": current.uncovered_regions}
                    if current.uncovered_regions
                    else {}
                ),
            }
        )
    return result


def visible_body_regions(raw_profile: Any, inventory: Any, *, equipment: Any = None) -> set[Region]:
    """Conservative coverage for already evidenced surface traces, never proof of undress."""
    profile = load_profile(raw_profile)
    if profile is None or not profile.wear_assessment_complete:
        return set()
    items = owned_items(inventory, equipment=equipment)
    if any(worn.item_id not in items for worn in profile.worn):
        return set()
    worn = _worn_items(profile, items, equipment)
    garments = [(entry, garment_for_item(items[entry.item_id])) for entry in worn]
    possible = _unassessed(profile, items)
    if any(garment is None for _, garment in garments) or any(
        garment is None for garment in possible
    ):
        return set()
    blocked: set[Region] = set()
    blocked.update(
        region
        for garment in possible
        if garment is not None and garment.opaque
        for region in garment.coverage
    )
    for entry, garment in garments:
        if garment is None or not set(entry.uncovered_regions).issubset(garment.coverage):
            return set()
        if garment.opaque:
            blocked.update(_covered(garment, entry))
    return set(REGIONS) - blocked
