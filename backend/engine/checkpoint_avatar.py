"""Restore the avatar projection using the checkpoint's existing legacy defaults."""

from copy import deepcopy

from backend.models.avatar import Avatar

_NUMBERS = (
    "hp",
    "max_hp",
    "stamina",
    "max_stamina",
    "mana",
    "max_mana",
    "exp",
    "strength",
    "intelligence",
    "wisdom",
    "dexterity",
    "charisma",
    "armor_class",
)


def restore(avatar: Avatar, snapshot: dict) -> None:
    for field in _NUMBERS:
        setattr(avatar, field, int(snapshot.get(field, getattr(avatar, field))))
    for field, default in (
        ("stats", {}),
        ("inventory", []),
        ("equipment", {}),
        ("status_effects", []),
    ):
        setattr(avatar, field, deepcopy(snapshot.get(field) or default))
    for field in ("gender", "age_years", "visual_profile"):
        setattr(avatar, field, deepcopy(snapshot.get(field)))
