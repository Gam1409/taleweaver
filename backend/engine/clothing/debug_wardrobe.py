"""Explicit wardrobe corrections reuse canonical wear and world-item transfers."""

from copy import deepcopy
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from backend.engine.character_identity import identity_profile
from backend.engine.clothing.context import resolved_inventory
from backend.engine.clothing.profiles import (
    garment_for_item,
    load_profile,
    owned_items,
    validate_profile,
)
from backend.engine.clothing.schema import VisualProfile, WornItem
from backend.engine.clothing.visuals import detailed_for_state
from backend.engine.narrated_items.wear import validate_wear
from backend.engine.rule_engine import GameEvent
from backend.engine.scene_staging.props import KEY as PROPS_KEY
from backend.engine.visual_novel.continuity import CanonicalInventoryItem
from backend.engine.visual_novel.ownership import sync_vn_ownership
from backend.models.world_entity import WorldEntity


class WardrobeAction(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    npc_id: str = Field(min_length=1, max_length=100)
    item_id: str = Field(min_length=1, max_length=100)
    operation: Literal["wear", "carry", "place"]
    spatial_position: str = Field(default="", max_length=120)


def scene_items(npc: Any, entities: list, states: dict) -> list[dict]:
    scene = (states.get(npc.id) or {}).get("current_scene_id", npc.current_scene_id)
    result = []
    held: set[str] = set()
    for entity in entities:
        if entity.entity_type != "NPC":
            continue
        inventory = (states.get(entity.id) or {}).get(
            "inventory", entity.inventory or (entity.metadata_json or {}).get("inventory") or []
        )
        identifiers = (row.get("id") if isinstance(row, dict) else row for row in inventory)
        held.update(identifier for identifier in identifiers if isinstance(identifier, str))
    for entity in entities:
        override = states.get(entity.id) or {}
        if (
            entity.entity_type != "OBJECT"
            or entity.id in held
            or override.get("current_scene_id", entity.current_scene_id) != scene
        ):
            continue
        if override.get("is_in_inventory", entity.is_in_inventory) or override.get(
            "is_hidden", entity.is_hidden
        ):
            continue
        item = resolved_inventory([entity.id], entities, states)
        garment = garment_for_item(item[0]) if item else None
        if not item or item[0].get("property_owner_id") not in {None, npc.id}:
            continue
        item_type = override.get("item_type", entity.item_type) or item[0].get("item_type", "")
        if garment is None and str(item_type).upper() not in {
            "WEARABLE",
            "CLOTHING",
        }:
            continue
        result.append(
            {
                **item[0],
                "item_type": item_type,
                "clothing": garment.model_dump() if garment else None,
                "worn": False,
                "location": "scene",
                "scene_id": scene,
                "spatial_position": override.get("spatial_position", entity.spatial_position) or "",
            }
        )
    return result


async def command(
    db: Any, state: Any, args: str, user: Any = None, adventure: Any = None, avatar: Any = None
) -> str:
    if not state.is_debug_enabled:
        return "DEBUG ERROR: Enable debug mode first."
    try:
        request = WardrobeAction.model_validate_json(args.split(" ", 1)[1])
        return await apply(db, state, avatar, request)
    except (ValueError, IndexError) as exc:
        return f"DEBUG ERROR: Wardrobe was not changed: {exc}"


async def apply(db: Any, state: Any, avatar: Any, request: WardrobeAction) -> str:
    entities = list(
        await db.scalars(select(WorldEntity).where(WorldEntity.session_id == state.session_id))
    )
    npc = next(
        (row for row in entities if row.id == request.npc_id and row.entity_type == "NPC"), None
    )
    if npc is None:
        raise ValueError("NPC does not belong to this session.")
    if any(row.id == request.item_id and row.entity_type != "OBJECT" for row in entities):
        raise ValueError("This item ID conflicts with a character identity; no state was changed.")
    if avatar is not None and request.item_id in owned_items(
        avatar.inventory, equipment=avatar.equipment
    ):
        raise ValueError(
            "This item is carried by the player; transfer it before changing the NPC's wardrobe."
        )
    states = deepcopy(state.entity_states or {})
    override = states.get(npc.id) or {}
    inventory = deepcopy(
        override.get("inventory", npc.inventory or (npc.metadata_json or {}).get("inventory") or [])
    )
    resolved = resolved_inventory(inventory, entities, states)
    owned = owned_items(resolved)
    scene = override.get("current_scene_id", npc.current_scene_id)
    raw = identity_profile(npc, override.get("visual_profile", npc.visual_profile))
    profile = load_profile(raw)
    if profile is None and raw:
        raise ValueError("Repair the existing invalid visual profile before changing wear.")
    profile = profile or VisualProfile()
    if request.operation == "place":
        return await _place(
            db, state, avatar, request, npc, states, override, inventory, owned, profile, scene
        )
    item = owned.get(request.item_id)
    if item is None:
        available = {row["id"]: row for row in scene_items(npc, entities, states)}
        item = available.get(request.item_id) if scene == state.current_scene_id else None
        if item is None:
            raise ValueError(
                "The item is neither owned by this NPC nor available in their current room."
            )
        item = _canonical(item)
        inventory.append(deepcopy(item))
    profile.worn = [row for row in profile.worn if row.item_id != request.item_id]
    if request.operation == "wear":
        worn = WornItem(item_id=request.item_id)
        validate_wear(
            {"age_years": profile.appearance.age_years},
            item,
            profile,
            worn,
            detailed_for_state(state),
        )
        profile.worn.append(worn)
    item = _canonical(item)
    resolved = [row for row in resolved if row["id"] != request.item_id] + [item]
    profile = validate_profile(profile, resolved)
    states[npc.id] = {**override, "inventory": inventory, "visual_profile": profile.model_dump()}
    states[request.item_id] = {
        **states.get(request.item_id, {}),
        "is_in_inventory": True,
        "current_scene_id": scene,
        "vn_item_data": item,
    }
    _forget_placement(states, request.item_id)
    state.entity_states = states
    return f"DEBUG: {item.get('name', request.item_id)} is now {'worn' if request.operation == 'wear' else 'in inventory'} for {npc.name}."


async def _place(
    db: Any,
    state: Any,
    avatar: Any,
    request: WardrobeAction,
    npc: Any,
    states: dict,
    override: dict,
    inventory: list,
    owned: dict,
    profile: VisualProfile,
    scene: str,
) -> str:
    if avatar is None or scene != state.current_scene_id:
        raise ValueError("Placing an item requires the NPC and player in the current room.")
    if not request.spatial_position or request.item_id not in owned:
        raise ValueError("Choose an owned item and describe its position in the current room.")
    item = {
        **deepcopy(owned[request.item_id]),
        "property_owner_id": npc.id,
        "spatial_position": request.spatial_position,
    }
    profile.worn = [row for row in profile.worn if row.item_id != request.item_id]
    profile = validate_profile(profile, list(owned.values()))
    states[npc.id] = {**override, "inventory": inventory, "visual_profile": profile.model_dump()}
    event = GameEvent(spawned_items=[CanonicalInventoryItem.model_validate(item)])
    await sync_vn_ownership(db, state, avatar, event, states)
    _forget_placement(states, request.item_id)
    state.entity_states = states
    return f"DEBUG: {item['name']} belongs to {npc.name} and is placed {request.spatial_position}; it is no longer carried or worn."


def _forget_placement(states: dict, item_id: str) -> None:
    if isinstance(states.get(PROPS_KEY), dict):
        data = states[PROPS_KEY]
        data["items"] = [row for row in data.get("items", []) if row.get("item_id") != item_id]


def _canonical(item: dict) -> dict:
    return {
        key: value
        for key, value in item.items()
        if key not in {"worn", "location", "scene_id", "spatial_position"}
    }
