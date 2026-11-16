"""Host-only clothing views; never expose another character's inventory or hidden layers."""

from typing import Any

from backend.engine.character_identity import identity_profile
from backend.engine.chpm import context
from backend.engine.chpm.kernel import ChpmError
from backend.engine.clothing.context import resolved_inventory
from backend.engine.clothing.profiles import garment_for_item, load_profile, owned_items
from backend.engine.clothing.projection import visible_character
from backend.engine.clothing.visuals import detailed_for_state, session_objects


def project(actor: Any, state: Any, entities: list[Any]) -> dict:
    overrides = state.entity_states or {}
    changed = overrides.get(actor.id) or {}
    raw = identity_profile(
        actor, changed.get("visual_profile", getattr(actor, "visual_profile", None))
    )
    inventory = changed.get(
        "inventory", actor.inventory or (actor.metadata_json or {}).get("inventory")
    )
    unknown = {"status": "unknown", "clothing": [], "omitted": 0}
    profile = load_profile(raw)
    if profile is None or not isinstance(inventory, list):
        return unknown
    resolved = resolved_inventory(inventory, entities, overrides)
    equipment = changed.get("equipment", getattr(actor, "equipment", None))
    items = owned_items(resolved, equipment=equipment)
    if any(w.item_id not in items for w in profile.worn):
        return unknown
    visible = visible_character(
        raw, resolved, detailed=detailed_for_state(state), equipment=equipment
    )
    if visible is None:
        return unknown
    garments = []
    for item in visible["clothing"]:
        garment = garment_for_item(items[item["item_id"]])
        if garment is not None:
            garments.append(
                {**item, "description": item["description"][:240], "layer": garment.layer}
            )
    return {
        "status": "limited" if visible["clothing_detail_limited"] else "known",
        "clothing": garments,
        "omitted": 0,
    }


async def capture(manager: Any) -> dict[str, dict]:
    if getattr(manager.state, "session_id", manager.game_id) != manager.game_id:
        raise ChpmError("CHPM clothing view belongs to another session.")
    entities = await session_objects(manager.db, manager.game_id)
    return {
        actor.id: {"name": str(actor.name)[:160], **project(actor, manager.state, entities)}
        for actor in entities
        if context.available(actor, manager.state)
    }
