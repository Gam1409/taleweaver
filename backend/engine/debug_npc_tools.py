"""Explicit session-only NPC placement and wardrobe corrections for the debug panel."""

import json
import shlex
from copy import deepcopy
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.engine.clothing.context import resolved_inventory
from backend.engine.clothing.profiles import (
    garment_for_item,
    load_profile,
    owned_items,
    validate_profile,
)
from backend.engine.clothing.schema import Garment, VisualProfile, WornItem
from backend.models.session_state import SessionState
from backend.models.world_entity import WorldEntity, WorldScene


class WardrobeEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    npc_id: str = Field(min_length=1, max_length=100)
    item_id: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(max_length=1000)
    clothing: Garment
    worn: bool


def wardrobe_info(entity: WorldEntity, entities: list[WorldEntity], states: dict) -> dict:
    override = states.get(entity.id, {})
    inventory = override.get(
        "inventory", entity.inventory or (entity.metadata_json or {}).get("inventory") or []
    )
    items = owned_items(resolved_inventory(inventory, entities, states))
    raw = override.get("visual_profile", entity.visual_profile)
    profile = load_profile(raw)
    worn = {row.item_id for row in profile.worn} if profile else set()
    clothes = []
    for identifier, item in items.items():
        garment = garment_for_item(item)
        if (
            garment is None
            and identifier not in worn
            and str(item.get("item_type", "")).upper() not in {"CLOTHING", "WEARABLE"}
        ):
            continue
        clothes.append(
            {
                **item,
                "clothing": garment.model_dump() if garment else None,
                "worn": identifier in worn,
                "uncovered_regions": next(
                    (row.uncovered_regions for row in profile.worn if row.item_id == identifier), []
                )
                if profile
                else [],
            }
        )
    preview = states.get("__wardrobe_recovery__") or {}
    recovery = None
    if preview.get("npc_id") == entity.id:
        recovery = {
            key: preview.get(key)
            for key in ("token", "notes", "messages_scanned", "limited", "accepted", "errors")
        }
    return {"items": clothes, "profile_known": profile is not None, "recovery": recovery}


async def _npc(db: AsyncSession, state: SessionState, identifier: str) -> WorldEntity | None:
    npc: WorldEntity | None = await db.scalar(
        select(WorldEntity).where(
            WorldEntity.session_id == state.session_id,
            WorldEntity.entity_type == "NPC",
            WorldEntity.id == identifier,
        )
    )

    return npc


async def debug_move_npc(
    db: AsyncSession,
    state: SessionState,
    args: str,
    user: Any = None,
    adventure: Any = None,
    avatar: Any = None,
) -> str:
    if not state.is_debug_enabled:
        return "DEBUG ERROR: Enable debug mode first."
    try:
        parts = shlex.split(args)
    except ValueError:
        parts = []
    if len(parts) != 3:
        return 'DEBUG ERROR: Usage: /debug move_npc "NPC_ID" "SCENE_ID"'
    npc = await _npc(db, state, parts[1])
    scene = await db.scalar(
        select(WorldScene).where(
            WorldScene.session_id == state.session_id, WorldScene.id == parts[2]
        )
    )
    if npc is None or scene is None:
        return "DEBUG ERROR: NPC or destination does not belong to this session."
    states = deepcopy(state.entity_states or {})
    states[npc.id] = {
        **states.get(npc.id, {}),
        "current_scene_id": scene.id,
        "spatial_position": None,
        "presence": "present",
    }
    # Poses and relative placements from before a manual move are no longer confirmed.
    states.pop("__scene_staging__", None)
    state.entity_states = states
    return f"DEBUG: Moved {npc.name} [{npc.id}] to {scene.label or scene.id} [{scene.id}]. Visibility and health unchanged."


async def debug_npc_clothing(
    db: AsyncSession,
    state: SessionState,
    args: str,
    user: Any = None,
    adventure: Any = None,
    avatar: Any = None,
) -> str:
    if not state.is_debug_enabled:
        return "DEBUG ERROR: Enable debug mode first."
    try:
        edit = WardrobeEdit.model_validate(json.loads(args.split(" ", 1)[1]))
        return await _edit_clothing(db, state, edit)
    except (ValueError, ValidationError, IndexError) as exc:
        return f"DEBUG ERROR: Clothing was not changed: {exc}"


async def _edit_clothing(db: AsyncSession, state: SessionState, edit: WardrobeEdit) -> str:
    npc = await _npc(db, state, edit.npc_id)
    if npc is None:
        raise ValueError("NPC does not belong to this session.")
    entities = list(
        await db.scalars(select(WorldEntity).where(WorldEntity.session_id == state.session_id))
    )
    states = deepcopy(state.entity_states or {})
    override = states.get(npc.id, {})
    inventory = override.get(
        "inventory", npc.inventory or (npc.metadata_json or {}).get("inventory") or []
    )
    items = owned_items(resolved_inventory(inventory, entities, states))
    if edit.item_id not in items:
        raise ValueError("The selected item is not owned by this NPC.")
    item = {
        **items[edit.item_id],
        "name": edit.name,
        "description": edit.description,
        "clothing": edit.clothing.model_dump(),
    }
    # Keep gameplay fields from the inline copy, including slots and runtime provenance.
    original = owned_items(inventory).get(edit.item_id, {})
    item = {**original, **item}
    items[edit.item_id] = item
    raw = override.get("visual_profile", npc.visual_profile)
    profile = load_profile(raw)
    if profile is None and raw:
        raise ValueError("Existing visual profile is invalid; repair it before editing clothing.")
    profile = profile or VisualProfile()
    uncovered = next(
        (row.uncovered_regions for row in profile.worn if row.item_id == edit.item_id), []
    )
    profile.worn = [row for row in profile.worn if row.item_id != edit.item_id]
    if edit.worn:
        profile.worn.append(
            WornItem(
                item_id=edit.item_id,
                uncovered_regions=[
                    region for region in uncovered if region in edit.clothing.coverage
                ],
            )
        )
    profile = validate_profile(profile.model_dump(), list(items.values()))
    # Update only the edited entry; preserve unrelated inventory representations/metadata.
    updated = [
        item if (row.get("id") if isinstance(row, dict) else row) == edit.item_id else row
        for row in inventory
    ]
    states[npc.id] = {**override, "inventory": updated, "visual_profile": profile.model_dump()}
    if any(row.id == edit.item_id and row.entity_type == "OBJECT" for row in entities):
        states[edit.item_id] = {
            **states.get(edit.item_id, {}),
            "name": edit.name,
            "description": edit.description,
            "clothing": edit.clothing.model_dump(),
            "vn_item_data": item,
        }
    state.entity_states = states
    return f"DEBUG: Updated {edit.name} for {npc.name}: {'worn' if edit.worn else 'in inventory'}."
