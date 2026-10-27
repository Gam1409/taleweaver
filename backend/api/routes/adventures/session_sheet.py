import logging
import os
from dataclasses import asdict
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import settings
from backend.core.game_modes import mode_policy
from backend.engine.clothing.presentation import player_clothing
from backend.engine.item_logic import get_item_slot, normalize_equipment_keys
from backend.models.adventure_template import AdventureTemplate
from backend.models.avatar import Avatar
from backend.models.session_state import SessionState
from backend.models.world_entity import WorldEntity, WorldScene
from backend.utils.path_security import (
    data_url_to_local_path,
)

logger = logging.getLogger(__name__)


async def build_sheet_snapshot(avatar: Avatar, state: SessionState, db: AsyncSession) -> dict:
    """Builds a serialisable character-sheet snapshot."""

    from .logic import AdventureLogic

    adv_res = await db.execute(
        select(AdventureTemplate).where(AdventureTemplate.id == state.template_id)
    )
    adventure = adv_res.scalars().first()
    session_snapshot = AdventureLogic.extract_manifest_snapshot(state)
    session_manifest = AdventureLogic.resolve_manifest_for_state(state)
    start_datetime = _sheet_start_datetime(adventure, state, session_snapshot, session_manifest)
    img_map = await _sheet_item_images(db, state)
    entity_lookup = await _sheet_inventory_entities(db, avatar, state)
    synced_inventory = _sheet_inventory(avatar.inventory, entity_lookup, img_map)
    synced_equipment = _sheet_equipment(avatar.equipment, entity_lookup, img_map)

    current_scene = await _sheet_current_scene(db, state)
    from backend.engine.stat_aggregator import calculate_total_stats

    total_stats = calculate_total_stats(avatar)

    profile_image = await _sheet_profile_image(db, avatar, state, session_manifest)
    snapshot = {
        "clothing": player_clothing(avatar, session_manifest),
        "name": avatar.name,
        "role": avatar.role,
        "description": avatar.description,
        "profile_image": profile_image,
        "hp": avatar.hp,
        "max_hp": avatar.max_hp,
        "stamina": avatar.stamina,
        "max_stamina": avatar.max_stamina,
        "mana": avatar.mana,
        "max_mana": avatar.max_mana,
        "strength": total_stats.get("strength", avatar.strength),
        "dexterity": total_stats.get("dexterity", avatar.dexterity),
        "intelligence": total_stats.get("intelligence", avatar.intelligence),
        "wisdom": total_stats.get("wisdom", avatar.wisdom),
        "charisma": total_stats.get("charisma", avatar.charisma),
        "armor_class": total_stats.get("armor_class", avatar.armor_class),
        "stats": total_stats,
        "inventory": synced_inventory,
        "equipment": synced_equipment,
        "status_effects": avatar.status_effects or [],
        "in_game_time": state.in_game_time,
        "start_datetime": start_datetime,
        "current_scene": current_scene.label if current_scene else state.current_scene_id,
        "special_actions": avatar.stats.get("special_actions") or [],
        "unlocked_actions": avatar.stats.get("unlocked_actions") or [],
        "scene_id": state.current_scene_id,
        "adventure_title": adventure.title if adventure else "Unknown",
        "adventure_version": adventure.version if adventure else None,
        "creator": adventure.creator if adventure else None,
        "copyright": adventure.copyright if adventure else None,
        "license": adventure.license if adventure else None,
        "license_url": adventure.license_url if adventure else None,
        "template_id": state.template_id,
        "exp": avatar.exp,
        "rule_enforcement_mode": adventure.rule_enforcement_mode
        if adventure
        else (session_snapshot.get("adventure") or {}).get("rule_enforcement_mode", "rpg"),
        "mode_capabilities": asdict(
            mode_policy(
                adventure.rule_enforcement_mode
                if adventure
                else (session_snapshot.get("adventure") or {}).get("rule_enforcement_mode", "rpg"),
                adventure.strict_rules
                if adventure
                else (session_snapshot.get("adventure") or {}).get("strict_rules"),
            )
        ),
        "adventure_tone": adventure.selected_tone
        if adventure
        else (session_snapshot.get("adventure") or {}).get("selected_tone"),
        "clock_enabled": bool(adventure.clock_enabled)
        if adventure
        else bool((session_snapshot.get("adventure") or {}).get("clock_enabled", False)),
        "time_system": state.time_system
        or (
            adventure.time_system
            if adventure
            else (session_snapshot.get("adventure") or {}).get("time_system", "relative")
        ),
        "time_config": state.time_config
        or (
            adventure.time_config
            if adventure
            else (session_snapshot.get("adventure") or {}).get("time_config")
        ),
        "time_per_turn": adventure.time_per_turn
        if adventure
        else (session_snapshot.get("adventure") or {}).get("time_per_turn", 5),
        "max_time_per_turn": adventure.max_time_per_turn
        if adventure
        else (session_snapshot.get("adventure") or {}).get("max_time_per_turn"),
        "max_memory_turns": getattr(state, "max_memory_turns", None)
        if getattr(state, "max_memory_turns", None) is not None
        else (getattr(adventure, "max_memory_turns", 10) if adventure else 10),
        "enable_history_compression": bool(getattr(state, "enable_history_compression", True)),
        "compressed_history": getattr(state, "compressed_history", None),
        "agent_active": bool((state.entity_states or {}).get("__agent__", {}).get("active", False)),
        "agent_monkey_mode": bool(
            (state.entity_states or {}).get("__agent__", {}).get("monkey_mode", False)
        ),
        "agent_allow_walkthrough": bool(
            (state.entity_states or {}).get("__agent__", {}).get("allow_walkthrough", True)
        ),
        "agent_step_by_step": bool(
            (state.entity_states or {}).get("__agent__", {}).get("step_by_step", False)
        ),
        "agent_personality": str(
            (state.entity_states or {}).get("__agent__", {}).get("personality", "casual")
        ),
        "agent_custom_personality": str(
            (state.entity_states or {}).get("__agent__", {}).get("custom_personality", "")
        ),
        "is_debug_enabled": bool(state.is_debug_enabled),
        "debug_mode": bool(settings.TALEWEAVER_DEBUG_ENABLED or state.is_debug_enabled),
    }
    return snapshot


def _sheet_start_datetime(adventure, state, session_snapshot, session_manifest):
    from .logic import AdventureLogic

    adventure_time_config = (
        adventure.time_config
        if adventure
        else (session_snapshot.get("adventure") or {}).get("time_config")
    )
    start_datetime = AdventureLogic.resolve_start_datetime(
        adventure.original_manifest if adventure else session_manifest,
        state=state,
        time_config=adventure_time_config,
    )

    if not start_datetime and (
        (adventure and adventure.clock_enabled)
        or bool((session_snapshot.get("adventure") or {}).get("clock_enabled"))
    ):
        resolved = AdventureLogic.resolve_start_datetime(
            {"time_config": adventure_time_config or {}},
            time_config=adventure_time_config,
        )
        start_datetime = resolved or "2026-04-17T08:00:00"

    return start_datetime


async def _sheet_item_images(db, state):
    from .logic import AdventureLogic

    snapshot = AdventureLogic.extract_asset_snapshot(state)
    has_asset_snapshot = "__asset_snapshot__" in (state.entity_states or {})
    snapshot_entity_images = snapshot.get("entity_images", {})

    res = await db.execute(
        select(WorldEntity.id, WorldEntity.image_url).where(
            WorldEntity.session_id == state.session_id, WorldEntity.image_url.is_not(None)
        )
    )
    img_map = {row.id: row.image_url for row in res.all() if row.id}
    if has_asset_snapshot:
        img_map = {k: v for k, v in snapshot_entity_images.items() if isinstance(v, str) and v}
    else:
        img_map.update(
            {k: v for k, v in snapshot_entity_images.items() if isinstance(v, str) and v}
        )

    return img_map


def _entity_to_item_dict(ent: WorldEntity) -> dict:
    """Build a minimal item dict from a WorldEntity for character sheet display."""
    guessed_slot = get_item_slot(ent.name or "", ent.item_type or "PICKABLE")
    wearable = ent.wearable_slots
    if isinstance(wearable, list) and wearable:
        item_slot = wearable[0]
    elif isinstance(wearable, str):
        item_slot = wearable
    else:
        item_slot = guessed_slot
    metadata = ent.metadata_json or {}
    effects = metadata.get("effects") if isinstance(metadata.get("effects"), dict) else {}

    def _get_val(*candidates):
        for c in candidates:
            if c is not None:
                try:
                    return int(c)
                except (TypeError, ValueError):
                    pass
        return None

    def _get_str(*candidates):
        for c in candidates:
            if isinstance(c, str) and c.strip():
                return c.strip()
        return None

    return {
        "id": ent.id,
        "name": ent.name,
        "description": ent.description,
        "image_url": ent.image_url,
        "item_type": ent.item_type or "PICKABLE",
        "slot": item_slot,
        "metadata_json": dict(metadata),
        "stat_modifier_strength": _get_val(ent.stat_modifier_strength),
        "stat_modifier_dexterity": _get_val(ent.stat_modifier_dexterity),
        "stat_modifier_intelligence": _get_val(ent.stat_modifier_intelligence),
        "stat_modifier_wisdom": _get_val(ent.stat_modifier_wisdom),
        "stat_modifier_charisma": _get_val(ent.stat_modifier_charisma),
        "stat_modifier_armor_class": _get_val(ent.stat_modifier_armor_class),
        "hp_change": _get_val(metadata.get("hp_change"), effects.get("hp")),
        "stamina_change": _get_val(metadata.get("stamina_change"), effects.get("stamina")),
        "mana_change": _get_val(metadata.get("mana_change"), effects.get("mana")),
        "damage_dice": _get_str(metadata.get("damage_dice")),
        "weapon_cost_type": _get_str(metadata.get("weapon_cost_type")),
        "weapon_cost_value": _get_val(metadata.get("weapon_cost_value")),
    }


async def _sheet_inventory_entities(db, avatar, state):

    # Pre-load entity records for any string item IDs (legacy format: equipment stored as IDs)
    item_ids_to_resolve: set[str] = set()
    for _item in avatar.inventory or []:
        if isinstance(_item, str) and _item:
            item_ids_to_resolve.add(_item)
    normalized_eq_check = normalize_equipment_keys(avatar.equipment)
    for _slot, _item in normalized_eq_check.items():
        if isinstance(_item, str) and _item:
            item_ids_to_resolve.add(_item)

    entity_lookup: dict[str, Any] = {}
    if item_ids_to_resolve:
        ent_res = await db.execute(
            select(WorldEntity).where(WorldEntity.id.in_(item_ids_to_resolve))
        )
        for ent in ent_res.scalars().all():
            if ent.id not in entity_lookup:
                entity_lookup[ent.id] = ent
            elif ent.session_id == state.session_id:
                # Prefer session-bound entities over template entities
                entity_lookup[ent.id] = ent

    return entity_lookup


async def _sheet_current_scene(db, state):

    scene_res = await db.execute(
        select(WorldScene).where(
            WorldScene.id == state.current_scene_id, WorldScene.session_id == state.session_id
        )
    )
    current_scene = scene_res.scalars().first()
    if not current_scene:
        scene_res = await db.execute(
            select(WorldScene).where(
                WorldScene.id == state.current_scene_id, WorldScene.template_id == state.template_id
            )
        )
        current_scene = scene_res.scalars().first()

    return current_scene


async def _sheet_profile_image(db, avatar, state, session_manifest):
    from .logic import AdventureLogic

    profile_image = AdventureLogic.resolve_session_asset(state, "protagonist", avatar.profile_image)
    if profile_image and "/adventures/sessions/" in profile_image:
        abs_path = data_url_to_local_path(profile_image)
        if not abs_path or not os.path.isfile(abs_path):
            profile_image = AdventureLogic.heal_template_avatar_profile_image(
                state.template_id, profile_image
            )
    if not profile_image:
        manifest_protagonist = (
            session_manifest.get("protagonist") if isinstance(session_manifest, dict) else None
        )
        if isinstance(manifest_protagonist, dict):
            profile_image = AdventureLogic.resolve_existing_data_asset_url(
                manifest_protagonist.get("profile_image")
            )
    if not profile_image and state.template_id:
        avatar_image_res = await db.execute(
            select(Avatar.profile_image)
            .where(
                Avatar.template_id == state.template_id,
                Avatar.profile_image.is_not(None),
                Avatar.profile_image != "",
            )
            .order_by(Avatar.updated_at.desc())
            .limit(10)
        )
        for candidate in avatar_image_res.scalars().all():
            resolved = AdventureLogic.resolve_existing_data_asset_url(candidate)
            if resolved:
                profile_image = resolved
                break
    return profile_image


def _sheet_item(item, entity_lookup, img_map):
    """Hydrate one supported item payload without mutating inventory or equipment."""
    if isinstance(item, str):
        payload = (
            _entity_to_item_dict(entity_lookup[item]) if item in entity_lookup else {"name": item}
        )
    else:
        payload = item
    item_copy = dict(payload)
    if not item_copy.get("slot"):
        item_copy["slot"] = get_item_slot(
            item_copy.get("name", ""), item_copy.get("item_type", "PICKABLE")
        )
    item_id = item_copy.get("id")
    if item_id in img_map and not item_copy.get("image_url"):
        item_copy["image_url"] = img_map[item_id]
    return item_copy


def _sheet_inventory(inventory, entity_lookup, img_map):
    return [
        _sheet_item(item, entity_lookup, img_map)
        for item in (inventory or [])
        if isinstance(item, (str, dict))
    ]


def _sheet_equipment(equipment, entity_lookup, img_map):
    return {
        slot: _sheet_item(item, entity_lookup, img_map)
        if item and isinstance(item, (str, dict))
        else item
        for slot, item in normalize_equipment_keys(equipment).items()
    }
