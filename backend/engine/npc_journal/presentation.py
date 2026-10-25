"""Project NPCs for players without exposing private possessions or authored motives."""

from typing import Any

_PRIVATE_FIELDS = {
    "visual_profile",
    "inventory",
    "equipment",
    "starting_inventory",
    "starting_equipment",
    "notes",
    "goal",
    "character",
}


def _without_private_fields(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _without_private_fields(child)
            for key, child in value.items()
            if key not in _PRIVATE_FIELDS
        }
    if isinstance(value, list):
        return [_without_private_fields(child) for child in value]
    return value


def player_entity_view(entity: dict[str, Any]) -> dict[str, Any]:
    """Keep authored/debug/save data intact; only ordinary player payloads use this view."""
    if str(entity.get("entity_type", "")).upper() != "NPC":
        return entity
    return _without_private_fields(entity)


def npc_possession_ids(entities: list[dict[str, Any]]) -> set[str]:
    """Carried objects must not also appear as loose scene loot, even with stale flags."""
    ids: set[str] = set()
    for entity in entities:
        if str(entity.get("entity_type", "")).upper() != "NPC":
            continue
        for item in entity.get("inventory") or []:
            item_id = item.get("id") if isinstance(item, dict) else item
            if isinstance(item_id, str) and item_id.strip():
                ids.add(item_id.strip())
    return ids
