"""Canonical garment identity for completed actions, with existing detail gates."""

from backend.engine.clothing.classification import classify_garment
from backend.engine.clothing.profiles import garment_for_item, load_profile


def inner_details_allowed(raw_profile: dict | None, detailed: bool) -> bool:
    profile = load_profile(raw_profile)
    return bool(
        detailed
        and profile
        and profile.appearance.age_years is not None
        and profile.appearance.age_years >= 18
    )


def item_facts(item: dict, *, include_inner: bool) -> dict:
    name = str(item.get("name") or "")
    garment = garment_for_item(item)
    if garment and classify_garment(name, garment).underwear and not include_inner:
        return {}
    description = str(item.get("description") or "")
    if not description and garment:
        description = garment.description
    return {"name": name, "description": description}
