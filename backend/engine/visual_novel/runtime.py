"""Small integration helpers for completed VN turns."""

from typing import Any

from sqlalchemy import select

from backend.engine.scene_illustrations import capture_scene_snapshot
from backend.models.world_entity import WorldScene


def equipped_appearance(avatar: Any) -> str:
    """Describe worn/held items only, never the rest of the player's bag."""
    equipment = getattr(avatar, "equipment", None) or {}
    inventory = getattr(avatar, "inventory", None) or []
    if not isinstance(equipment, dict) or not isinstance(inventory, list):
        return ""
    items = {str(item.get("id")): item for item in inventory if isinstance(item, dict)}
    descriptions = []
    for slot, value in equipment.items():
        item = value if isinstance(value, dict) else items.get(str(value))
        if not item:
            continue
        name = str(item.get("name") or "").strip()
        if name:
            descriptions.append(f"{slot}: {name}. {str(item.get('description') or '')[:200]}")
    return "; ".join(descriptions)[:1000]


async def capture_completed_moment(manager: Any, message: Any) -> None:
    """Freeze the public cast at completion; never include hidden possessions or goals."""
    from backend.api.routes.adventures.logic import AdventureLogic

    # ChatMessage's insert hook stamps scene_id from the session on flush.
    await manager.db.flush([message])
    with manager.db.no_autoflush:
        entities = await AdventureLogic.build_session_entities(manager.db, manager.state)
        scene = await manager.db.scalar(
            select(WorldScene).where(
                WorldScene.session_id == manager.state.session_id,
                WorldScene.id == message.scene_id,
            )
        )
    facts = {
        "setting": scene.description if scene is not None else "",
        "characters": [
            {
                "id": manager.avatar.id,
                "name": manager.avatar.name,
                "appearance": manager.avatar.description,
                "clothing": equipped_appearance(manager.avatar),
            },
            *[
                {
                    "id": entity.get("id"),
                    "name": entity.get("name"),
                    "appearance": entity.get("description"),
                    "position": entity.get("spatial_position"),
                }
                for entity in entities
                if entity.get("entity_type") == "NPC" and not entity.get("is_defeated")
            ],
        ],
    }
    await capture_scene_snapshot(manager.db, manager.state, message, facts)
