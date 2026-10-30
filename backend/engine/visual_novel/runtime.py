"""Small integration helpers for completed VN turns."""

from typing import Any

from sqlalchemy import select

from backend.engine.clothing.context import resolved_inventory
from backend.engine.clothing.visuals import (
    character_visuals,
    detailed_for_state,
    session_objects,
)
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


def _npc_facts(entity: dict, rows: dict, state: Any, detailed: bool) -> dict:
    npc = rows.get(entity.get("id"))
    override = (state.entity_states or {}).get(entity.get("id")) or {}
    profile = override.get("visual_profile", getattr(npc, "visual_profile", None))
    metadata = getattr(npc, "metadata_json", None) or {}
    inventory = (
        override.get("inventory", getattr(npc, "inventory", None) or metadata.get("inventory", []))
        or []
    )
    projected = character_visuals(
        npc,
        resolved_inventory(inventory, list(rows.values()), state.entity_states or {}),
        profile=profile,
        detailed=detailed,
    )
    if projected is not None:
        projected["name"] = entity.get("name", projected["name"])
        projected["position"] = entity.get("spatial_position")
        return projected
    return {
        "id": entity.get("id"),
        "name": entity.get("name"),
        "appearance": entity.get("description"),
        "position": entity.get("spatial_position"),
    }


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
        rows = {
            entity.id: entity
            for entity in await session_objects(manager.db, manager.state.session_id)
        }
    detailed = detailed_for_state(manager.state)
    player = character_visuals(
        manager.avatar,
        resolved_inventory(
            manager.avatar.inventory or [], list(rows.values()), manager.state.entity_states or {}
        ),
        detailed=detailed,
    )
    player = player or {
        "id": manager.avatar.id,
        "name": manager.avatar.name,
        "appearance": manager.avatar.description,
        "clothing": equipped_appearance(manager.avatar),
    }
    facts = {
        "setting": scene.description if scene is not None else "",
        "characters": [
            player,
            *[
                _npc_facts(entity, rows, manager.state, detailed)
                for entity in entities
                if entity.get("entity_type") == "NPC" and not entity.get("is_defeated")
            ],
        ],
    }
    if any(person.get("managed_clothing") for person in facts["characters"]):
        # A scene label is enough to ground composition; its prose may describe hidden outfits.
        facts["setting"] = scene.label if scene is not None else ""
    await capture_scene_snapshot(manager.db, manager.state, message, facts)
