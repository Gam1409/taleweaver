"""Validate ownership and reconcile worn references without inventing clothing."""

from copy import deepcopy
from typing import Any

from pydantic import BaseModel, ValidationError

from backend.engine.clothing.schema import Garment, VisualProfile


def load_profile(raw: Any) -> VisualProfile | None:
    """Missing, malformed and unsupported profiles have no trusted visual projection."""
    if raw is None or raw == {}:
        return None
    try:
        return VisualProfile.model_validate(raw).model_copy(deep=True)
    except ValidationError:
        return None


def sanitize_garment(raw: Any) -> dict | None:
    try:
        return Garment.model_validate(raw).model_dump()
    except ValidationError:
        return None


def _item(raw: Any) -> dict | None:
    if isinstance(raw, BaseModel):
        raw = raw.model_dump(exclude_none=True)
    if isinstance(raw, str) and raw.strip():
        return {"id": raw.strip()}
    if not isinstance(raw, dict):
        return None
    identifier = raw.get("id")
    if not isinstance(identifier, str) or not identifier.strip():
        return None
    return {**deepcopy(raw), "id": identifier.strip()}


def _inventory_values(inventory: Any) -> list:
    if isinstance(inventory, dict):
        return list(inventory.values())
    return inventory if isinstance(inventory, list | tuple) else []


def owned_items(inventory: Any, *, equipment: Any = None) -> dict[str, dict]:
    """Inventory is authoritative; inline equipped items are also actual possessions."""
    result: dict[str, dict] = {}
    ambiguous: set[str] = set()
    for raw in _inventory_values(inventory):
        item = _item(raw)
        if item is None:
            continue
        identifier = item["id"]
        previous = result.get(identifier)
        if previous and len(previous) > 1 and len(item) > 1 and previous != item:
            ambiguous.add(identifier)
        if previous is None or len(previous) == 1:
            result[identifier] = item
    for raw in equipment.values() if isinstance(equipment, dict) else []:
        # A stale string reference alone cannot establish ownership.
        if not isinstance(raw, dict | BaseModel):
            continue
        item = _item(raw)
        if item is not None and item["id"] not in result:
            result[item["id"]] = item
    for identifier in ambiguous:
        result[identifier] = {"id": identifier}
    return result


def garment_for_item(item: dict) -> Garment | None:
    metadata = item.get("metadata_json")
    raw = (
        item.get("clothing")
        if "clothing" in item
        else (metadata.get("clothing") if isinstance(metadata, dict) else None)
    )
    sanitized = sanitize_garment(raw)
    return Garment.model_validate(sanitized) if sanitized is not None else None


def sanitize_inventory(items: Any) -> list[dict | str]:
    """Keep canonical items and ID references; remove malformed garment specifications."""
    result: list[dict | str] = []
    for raw in _inventory_values(items):
        if isinstance(raw, str):
            result.append(raw)
            continue
        item = raw.model_dump(exclude_none=True) if isinstance(raw, BaseModel) else deepcopy(raw)
        if not isinstance(item, dict):
            continue
        _sanitize_item_clothing(item)
        result.append(item)
    return result


def _sanitize_item_clothing(item: dict) -> None:
    # An explicit invalid canonical value must not revive a conflicting legacy
    # specification from metadata after it is removed.
    if "clothing" in item and sanitize_garment(item["clothing"]) is None:
        item.pop("clothing")
        if isinstance(item.get("metadata_json"), dict):
            item["metadata_json"].pop("clothing", None)
        return
    sources = [item]
    if isinstance(item.get("metadata_json"), dict):
        sources.append(item["metadata_json"])
    for source in sources:
        if "clothing" not in source:
            continue
        garment = sanitize_garment(source["clothing"])
        if garment is None:
            source.pop("clothing")
        else:
            source["clothing"] = garment


def validate_profile(raw: Any, inventory: Any, *, equipment: Any = None) -> VisualProfile:
    profile = VisualProfile.model_validate(raw)
    items = owned_items(inventory, equipment=equipment)
    for worn in profile.worn:
        if worn.item_id not in items:
            raise ValueError("Worn garments must belong to this character.")
        garment = garment_for_item(items[worn.item_id])
        if garment is None:
            raise ValueError("Worn items require valid garment metadata.")
        if not set(worn.uncovered_regions).issubset(garment.coverage):
            raise ValueError("Uncovered regions must be part of the garment's coverage.")
    return profile.model_copy(deep=True)


def reconcile_profile(raw: Any, inventory: Any, *, equipment: Any = None) -> dict | None:
    """Clear lost possessions; keep unknown owned coverage conservative until repaired."""
    profile = load_profile(raw)
    if profile is None:
        return None
    items = owned_items(inventory, equipment=equipment)
    kept = []
    for worn in profile.worn:
        if worn.item_id not in items:
            continue
        garment = garment_for_item(items[worn.item_id])
        if garment is not None:
            worn.uncovered_regions = [r for r in worn.uncovered_regions if r in garment.coverage]
        kept.append(worn)
    profile.worn = kept
    return profile.model_dump()
