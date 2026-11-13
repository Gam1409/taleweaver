"""Expose declared placement availability without turning missing evidence into emptiness."""

from backend.engine.clothing.body_schema import BODY_SLOT_KEYS
from backend.engine.clothing.profiles import load_profile, owned_items


def placement_projection(
    actor: dict, equipment: list[dict], *, detailed: bool, conditions: list[dict] | None = None
) -> dict:
    """Explicit declarations and confirmed public facts establish display groups."""
    profile = load_profile(actor.get("visual_profile"))
    age = profile.appearance.age_years if profile else None
    if not detailed or profile is None or type(age) is not int or age < 18:
        return {}
    allowed = profile.body.attachment_slots if profile.body else None
    status = "unassessed" if allowed is None else ("available" if allowed else "unavailable")
    states = {BODY_SLOT_KEYS[slot]: "empty" for slot in allowed or []}
    if allowed is None:
        states.update(
            {
                key: "empty"
                for row in conditions or []
                if row.get("target_id") == actor["id"]
                for key in row.get("display_slots", [])
                if key in BODY_SLOT_KEYS.values()
            }
        )
    owned = owned_items(actor.get("resolved_inventory"))
    for row in profile.worn:
        if (
            row.attachment_slot
            and row.item_id in owned
            and BODY_SLOT_KEYS[row.attachment_slot] in states
        ):
            states[BODY_SLOT_KEYS[row.attachment_slot]] = "unconfirmed"
    occupied = {
        key for item in equipment for key in item.get("slots", []) if key in BODY_SLOT_KEYS.values()
    }
    for key in occupied:
        if allowed is None or key in states:
            states[key] = "occupied"
    return {
        "placement_status": status,
        "placement_slots": [
            {"key": key, "status": states[key]} for key in BODY_SLOT_KEYS.values() if key in states
        ],
    }
