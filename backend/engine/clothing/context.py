"""Private wardrobe context for the existing VN continuity call, never a UI payload."""

from copy import deepcopy
from typing import Any

from backend.engine.clothing.profiles import garment_for_item, load_profile, owned_items
from backend.engine.clothing.visuals import canonical_inventory, detailed_for_state
from backend.engine.npc_presence import physically_present
from backend.engine.visual_novel.continuity import PLAYER, possession_snapshot


def detail_settings(manager: Any) -> dict[str, bool]:
    return {
        "detailed": detailed_for_state(manager.state)
        if hasattr(manager.state, "entity_states")
        else False
    }


def resolved_inventory(inventory: list, entities: list[Any], states: dict) -> list[dict]:
    objects = []
    for entity in entities:
        if entity.entity_type != "OBJECT":
            continue
        override = states.get(entity.id, {})
        objects.append(
            {
                "id": entity.id,
                "name": entity.name,
                "description": getattr(entity, "description", ""),
                "metadata_json": getattr(entity, "metadata_json", None) or {},
                **override,
            }
        )
    return canonical_inventory(inventory, objects)


def actor_records(manager: Any, entities: list[Any], states: dict | None = None) -> dict[str, dict]:
    states = (getattr(manager.state, "entity_states", None) or {}) if states is None else states
    avatar = manager.avatar
    records = {
        PLAYER: {
            "id": PLAYER,
            "name": getattr(avatar, "name", ""),
            "description": str(getattr(avatar, "description", "") or "")[:1800],
            "inventory": deepcopy(getattr(avatar, "inventory", None) or []),
            "equipment": deepcopy(getattr(avatar, "equipment", None) or {}),
            "visual_profile": deepcopy(getattr(avatar, "visual_profile", None)),
        }
    }
    for entity in entities:
        override = states.get(entity.id, {})
        if not isinstance(override, dict):
            override = {}
        if (
            entity.entity_type != "NPC"
            or not physically_present(
                {"entity_type": "NPC", "presence": override.get("presence", "present")}
            )
            or override.get("current_scene_id", entity.current_scene_id)
            != manager.state.current_scene_id
            or override.get("is_hidden", getattr(entity, "is_hidden", False))
            or override.get("is_defeated", getattr(entity, "is_defeated", False))
        ):
            continue
        metadata = getattr(entity, "metadata_json", None) or {}
        records[entity.id] = {
            "id": entity.id,
            "name": entity.name,
            "description": str(
                override.get("description", getattr(entity, "description", "")) or ""
            )[:1800],
            "inventory": deepcopy(
                override.get("inventory", entity.inventory or metadata.get("inventory") or [])
            ),
            "equipment": {},
            "visual_profile": deepcopy(
                override.get("visual_profile", getattr(entity, "visual_profile", None))
            ),
            "private_character": str(getattr(entity, "character", "") or "")[:700],
            "private_goal": str(getattr(entity, "goal", "") or "")[:400],
        }
    for actor in records.values():
        actor["resolved_inventory"] = resolved_inventory(actor["inventory"], entities, states)
    return records


def source_records(manager: Any, entities: list[Any], scenes: list[Any]) -> dict[str, dict]:
    snapshot = possession_snapshot(manager, entities)
    records = {}
    for entity in entities:
        if entity.id not in snapshot.npcs and entity.id not in snapshot.containers:
            continue
        override = (manager.state.entity_states or {}).get(entity.id, {})
        records[entity.id] = {
            "id": entity.id,
            "kind": "container" if entity.id in snapshot.containers else "npc",
            "description": str(
                override.get("description", getattr(entity, "description", "")) or ""
            )[:1800],
        }
    for scene in scenes:
        data = (
            scene if isinstance(scene, dict) else {"id": scene.id, "description": scene.description}
        )
        if data.get("id") == manager.state.current_scene_id:
            records[data["id"]] = {
                "id": data["id"],
                "kind": "scene",
                "description": str(data.get("description") or "")[:1800],
            }
    return records


def build_clothing_context(manager: Any, entities: list[Any], scenes: list[Any]) -> dict:
    actors = actor_records(manager, entities)
    for actor in actors.values():
        profile = load_profile(actor.pop("visual_profile"))
        actor["visual_profile"] = profile.model_dump() if profile else None
        actor["owned_garments"] = [
            {
                "id": item["id"],
                "name": item.get("name", ""),
                "clothing": garment_for_item(item).model_dump(),
            }
            for item in owned_items(
                actor.pop("resolved_inventory"), equipment=actor.pop("equipment")
            ).values()
            if garment_for_item(item) is not None
        ][:48]
        actor.pop("inventory")
    return {
        "settings": detail_settings(manager),
        "player_actor_id": PLAYER,
        "actors": list(actors.values())[:12],
        "sources": list(source_records(manager, entities, scenes).values())[:20],
    }
