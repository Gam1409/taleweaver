"""Freeze already visibility-filtered room objects separately from possessions."""

from typing import Any


def room_objects(entities: list[dict], scene: Any) -> list[dict]:
    objects = [
        {
            "item_id": str(entity["id"]),
            "name": entity.get("name") or "",
            "description": entity.get("description") or "",
            "spatial_position": entity.get("spatial_position") or "",
        }
        for entity in entities
        if entity.get("entity_type") == "OBJECT"
        and not entity.get("is_hidden")
        and not entity.get("is_in_inventory")
    ]
    decor = getattr(scene, "decorative_objects", None)
    decorations = [
        {"item_id": f"decor:{scene.id}:{index}", "name": item, "description": item}
        for index, item in enumerate(decor if isinstance(decor, list) else [])
        if isinstance(item, str) and item.strip()
    ]
    return objects + decorations


def bind_player(facts: dict, player_id: str) -> None:
    """Bind extraction's stable player alias to this snapshot's canonical cast ID."""
    for action in facts.get("visible_actions", []):
        action["actor_ids"] = [
            player_id if value == "__player__" else value for value in action["actor_ids"]
        ]
    _bind_entries(facts.get("scene_facts", []), ("subject_id",), player_id)
    _bind_entries(facts.get("physical_conditions", []), ("target_id", "actor_id"), player_id)


def _bind_entries(rows: list[dict], keys: tuple[str, ...], player_id: str) -> None:
    for row in rows:
        row.update({key: player_id for key in keys if row.get(key) == "__player__"})
