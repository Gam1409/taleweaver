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
