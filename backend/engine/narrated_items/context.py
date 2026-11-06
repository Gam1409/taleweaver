"""Compact identification context; authoritative item hydration stays on the host."""

from typing import Any

_ITEM_FIELDS = (
    "id",
    "name",
    "description",
    "item_type",
    "clothing",
    "wearable_slots",
    "spatial_position",
    "condition_note",
)


def actor_context(actors: dict) -> list[dict]:
    result = []
    for actor in actors.values():
        row = {key: actor.get(key) for key in ("id", "name", "age_years")}
        profile = actor.get("visual_profile")
        if isinstance(profile, dict):
            row["visual_profile"] = {"worn": profile.get("worn", [])}
        result.append(row)
    return result


def item_context(items: dict[str, dict[str, Any]]) -> dict[str, dict]:
    # Scripts, provenance and arbitrary extension metadata are retained in the
    # authoritative snapshot, not copied into a model identification request.
    return {
        identifier: {key: item[key] for key in _ITEM_FIELDS if key in item}
        for identifier, item in items.items()
    }
