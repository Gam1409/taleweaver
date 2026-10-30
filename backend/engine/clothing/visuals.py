"""Image-facing appearance projection; raw biography and private wardrobes never escape."""

from typing import Any

from sqlalchemy import select

from backend.engine.clothing.projection import visible_character
from backend.engine.clothing.settings import clothing_settings
from backend.models.world_entity import WorldEntity


def value(actor: Any, key: str, default: Any = None) -> Any:
    return actor.get(key, default) if isinstance(actor, dict) else getattr(actor, key, default)


def canonical_inventory(inventory: list, entities: list) -> list[dict]:
    """Resolve only owned references; canonical object fields supersede stale item copies."""
    by_id = {str(value(entity, "id")): entity for entity in entities}
    result = []
    for item in inventory or []:
        item_id = str(item.get("id")) if isinstance(item, dict) else str(item)
        canonical = by_id.get(item_id)
        if canonical is None:
            result.append(item if isinstance(item, dict) else {"id": item_id})
            continue
        item_data = {
            "id": item_id,
            "name": value(canonical, "name", ""),
            "description": value(canonical, "description", ""),
            "metadata_json": value(canonical, "metadata_json", {}),
        }
        garment = value(canonical, "clothing")
        if garment is not None or isinstance(canonical, dict) and "clothing" in canonical:
            item_data["clothing"] = garment
        result.append(item_data)
    return result


def character_visuals(
    actor: Any, inventory: list, *, profile: dict | None = None, detailed: bool = False
) -> dict | None:
    """None means legacy. A present invalid profile yields an empty safe projection."""
    raw = profile if profile is not None else value(actor, "visual_profile")
    if raw is None:
        return None
    projected = visible_character(
        raw, inventory, detailed=detailed, equipment=value(actor, "equipment")
    ) or {"appearance": {}, "clothing": [], "clothing_detail_limited": True}
    appearance = projected["appearance"]
    appearance_text = "; ".join(
        f"{key}: {field}" for key, field in appearance.items() if field not in (None, "", [])
    )
    clothing = "; ".join(_garment_description(item) for item in projected["clothing"])
    limited = projected["clothing_detail_limited"] or not projected["clothing"]
    if limited:
        clothing += "; Other clothing details are unspecified; do not infer undress."
    return {
        "id": str(value(actor, "id", "")),
        "name": value(actor, "name", ""),
        "appearance": appearance_text,
        "clothing": clothing,
        "managed_clothing": True,
        "clothing_detail_limited": limited,
    }


def _garment_description(item: dict) -> str:
    description = (
        f"{item['name']}: {item['description']}" if item.get("description") else item["name"]
    )
    return f"{description} (visible on: {', '.join(item['visible_regions'])})"


def portrait_description(facts: dict) -> str:
    return "; ".join(str(facts[key]) for key in ("appearance", "clothing") if facts.get(key))


def detailed_for_state(state: Any) -> bool:
    snapshot = (state.entity_states or {}).get("__manifest_snapshot__") or {}
    return clothing_settings(snapshot.get("original_manifest"))["detailed"]


async def session_objects(db, session_id: str) -> list[WorldEntity]:
    return list(
        (await db.scalars(select(WorldEntity).where(WorldEntity.session_id == session_id))).all()
    )


async def npc_visuals(db, state, npc) -> dict | None:
    from backend.engine.clothing.context import resolved_inventory

    override = (state.entity_states or {}).get(npc.id) or {}
    profile = override.get("visual_profile", value(npc, "visual_profile"))
    if profile is None:
        return None
    inventory = (
        override.get("inventory", npc.inventory or (npc.metadata_json or {}).get("inventory", []))
        or []
    )
    owned = resolved_inventory(
        inventory, await session_objects(db, state.session_id), state.entity_states or {}
    )
    facts = character_visuals(npc, owned, profile=profile, detailed=detailed_for_state(state))
    if facts is not None:
        facts["name"] = override.get("name", npc.name)
    return facts
