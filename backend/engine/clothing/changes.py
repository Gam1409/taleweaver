"""Owned wardrobe operations shared by validated narration and actor commands."""

from copy import deepcopy
from typing import Literal

from backend.engine.clothing.classification import classify_garment
from backend.engine.clothing.profiles import (
    garment_for_item,
    load_profile,
    owned_items,
    validate_profile,
)
from backend.engine.clothing.resolution_facts import inner_details_allowed
from backend.engine.clothing.schema import Region, VisualProfile, WornItem

Operation = Literal["wear", "remove", "adjust"]


def _profile(actor: dict) -> VisualProfile:
    current = actor["visual_profile"]
    profile = load_profile(current)
    if profile is None and current:
        raise ValueError("Unsupported visual profile was preserved.")
    return profile or VisualProfile()


def _id(value: object) -> object:
    return value.get("id") if isinstance(value, dict) else value


def mutate(
    actor: dict, item_id: str, operation: Operation, uncovered_regions: list[Region]
) -> None:
    """Change an already authorized working copy; callers own policy/source validation."""
    if operation not in {"wear", "remove", "adjust"}:
        raise ValueError("Unsupported wardrobe operation.")
    profile = _profile(actor)
    items = owned_items(actor["resolved_inventory"], equipment=actor["equipment"])
    if item_id not in items:
        raise ValueError("The character does not own that garment.")
    worn = {item.item_id: item for item in profile.worn}
    equipped = {_id(value) for value in actor["equipment"].values()}
    if operation != "wear" and item_id not in worn and item_id not in equipped:
        raise ValueError("That garment is not currently worn.")
    if operation == "remove":
        worn.pop(item_id, None)
    else:
        worn[item_id] = WornItem(item_id=item_id, uncovered_regions=uncovered_regions)
    profile.worn = list(worn.values())
    actor["visual_profile"] = validate_profile(
        profile, actor["resolved_inventory"], equipment=actor["equipment"]
    ).model_dump()
    if operation != "remove":
        return
    if item_id not in {_id(row) for row in actor["inventory"]}:
        actor["inventory"].append(deepcopy(items[item_id]))
    if item_id not in {_id(row) for row in actor["resolved_inventory"]}:
        actor["resolved_inventory"].append(deepcopy(items[item_id]))
    actor["equipment"] = {
        slot: None if _id(value) == item_id else value for slot, value in actor["equipment"].items()
    }


def preview(
    actor: dict,
    item_id: str,
    operation: Operation,
    uncovered_regions: list[Region],
    *,
    detailed: bool,
) -> dict:
    """Validate on a copy without fabricating narration or changing the previous actor."""
    item = owned_items(actor["resolved_inventory"], equipment=actor["equipment"]).get(item_id)
    garment = garment_for_item(item or {})
    if garment is not None:
        garment = classify_garment(str((item or {}).get("name") or ""), garment)
    if (
        operation != "remove"
        and garment is not None
        and garment.underwear
        and not inner_details_allowed(actor["visual_profile"], detailed)
    ):
        raise ValueError(
            "Detailed garment tracking is unavailable for current settings or known age."
        )
    changed = deepcopy(actor)
    mutate(changed, item_id, operation, uncovered_regions)
    return changed
