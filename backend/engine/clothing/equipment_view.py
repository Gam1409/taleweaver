"""Presentation slots are a projection of canonical wear, never a second equipment store."""

from typing import Any

from backend.engine.clothing.profiles import load_profile
from backend.engine.item_logic import normalize_equipment_keys

_REGION_SLOT = {
    "head": "Head",
    "torso": "Chest",
    "arms": "Arms",
    "pelvis": "Legs",
    "legs": "Legs",
    "feet": "Feet",
    "hands": "Hands",
}
_GENDER_VARIANTS = {
    "male": "male",
    "man": "male",
    "мужской": "male",
    "мужчина": "male",
    "муж": "male",
    "м": "male",
    "female": "female",
    "woman": "female",
    "женский": "female",
    "женщина": "female",
    "жен": "female",
    "ж": "female",
}


def layout(profile: Any, *, gender: str | None = None, npc_type: str | None = None) -> dict:
    parsed = load_profile(profile)
    body = parsed.body if parsed else None
    form = (
        body.form
        if body
        else {"HUMANOID": "humanoid", "ANIMAL": "non_humanoid"}.get(npc_type or "", "unknown")
    )
    silhouette = (body.silhouette if body else None) or _GENDER_VARIANTS.get(
        (gender or "").strip().casefold(), "neutral"
    )
    return {"form": form, "silhouette": silhouette}


def display_slots(raw_slots: Any, coverage: list[str]) -> list[str]:
    values = [raw_slots] if isinstance(raw_slots, str) else raw_slots
    supplied = [value for value in values or [] if isinstance(value, str)]
    # wearable_slots are alternatives, not a command to duplicate one garment on the body.
    for value in supplied:
        valid = [key for key, present in normalize_equipment_keys({value: True}).items() if present]
        if valid:
            return [valid[0]]
    for region in coverage:
        if region in _REGION_SLOT:
            return [_REGION_SLOT[region]]
    return []
