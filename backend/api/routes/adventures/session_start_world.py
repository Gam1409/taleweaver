import logging
from copy import deepcopy

from sqlalchemy import select

from backend.models.world_entity import WorldEntity, WorldExit, WorldScene

logger = logging.getLogger(__name__)


async def clone_template_world(
    db, template_id, new_session, avatar, asset_copy_cache, entity_images
):
    from .sessions import _copy_data_asset_to_session

    # --- DEEP CLONE WORLD DATA ---
    # 1. Clone Scenes
    scenes_res = await db.execute(
        select(WorldScene).where(
            WorldScene.template_id == template_id,
            WorldScene.session_id.is_(None),
        )
    )
    scenes = scenes_res.scalars().all()
    for s in scenes:
        copied_scene_image = _copy_data_asset_to_session(
            new_session.id, "scenes", s.image_url, asset_copy_cache
        )
        new_s = WorldScene(
            id=s.id,
            session_id=new_session.id,
            template_id=None,
            label=s.label,
            description=s.description,
            image_url=(copied_scene_image or s.image_url),
            decorative_objects=deepcopy(s.decorative_objects),
        )
        db.add(new_s)

    # 2. Clone Exits
    exits_res = await db.execute(
        select(WorldExit).where(
            WorldExit.template_id == template_id,
            WorldExit.session_id.is_(None),
        )
    )
    exits = exits_res.scalars().all()
    for e in exits:
        new_e = WorldExit(
            session_id=new_session.id,
            template_id=None,
            from_scene_id=e.from_scene_id,
            to_scene_id=e.to_scene_id,
            label=e.label,
            exit_type=e.exit_type,
            is_locked=e.is_locked,
            lock_description=e.lock_description,
            code_to_unlock=e.code_to_unlock,
            item_to_unlock=e.item_to_unlock,
            rule_to_unlock=e.rule_to_unlock,
        )
        db.add(new_e)

    # 3. Clone Entities
    entities_res = await db.execute(
        select(WorldEntity).where(
            WorldEntity.template_id == template_id,
            WorldEntity.session_id.is_(None),
        )
    )
    entities = entities_res.scalars().all()
    for ent in entities:
        copied_entity_image = entity_images.get(ent.id)
        if copied_entity_image is None:
            copied_entity_image = _copy_data_asset_to_session(
                new_session.id, "entities", ent.image_url, asset_copy_cache
            )

        # Determine consistent is_in_inventory state
        is_in_inventory = bool(ent.is_in_inventory)
        if ent.current_scene_id != "INVENTORY":
            is_in_inventory = False
        elif avatar and avatar.inventory:
            avatar_inv_ids = {
                (i if isinstance(i, str) else (i.get("id") if isinstance(i, dict) else None))
                for i in avatar.inventory
            }
            if ent.id not in avatar_inv_ids:
                is_in_npc = any(
                    ent.id
                    in {
                        (
                            ni
                            if isinstance(ni, str)
                            else (ni.get("id") if isinstance(ni, dict) else None)
                        )
                        for ni in (other.inventory or [])
                    }
                    for other in entities
                    if other.entity_type == "NPC" and other.inventory
                )
                if not is_in_npc:
                    is_in_inventory = False

        new_ent = WorldEntity(
            id=ent.id,
            session_id=new_session.id,
            template_id=None,
            entity_type=ent.entity_type,
            name=ent.name,
            description=ent.description,
            current_scene_id=ent.current_scene_id,
            spatial_position=ent.spatial_position,
            image_url=(copied_entity_image or ent.image_url),
            item_type=ent.item_type,
            wearable_slots=ent.wearable_slots,
            is_in_inventory=is_in_inventory,
            is_hidden=ent.is_hidden,
            unlock_rule=ent.unlock_rule,
            is_portable=ent.is_portable,
            combination_ingredients=ent.combination_ingredients,
            reveals_item_id=ent.reveals_item_id,
            is_final_state=ent.is_final_state,
            state_comment=ent.state_comment,
            npc_type=ent.npc_type,
            movement_type=ent.movement_type,
            moveable=bool(ent.moveable)
            if ent.moveable is not None
            else (str(ent.movement_type or "").upper() == "MOVABLE"),
            allowed_scenes=deepcopy(ent.allowed_scenes) if ent.allowed_scenes else [],
            notes=ent.notes,
            goal=ent.goal,
            character=ent.character,
            visual_profile=deepcopy(ent.visual_profile),
            hp=ent.hp,
            max_hp=ent.max_hp,
            mana=ent.mana,
            max_mana=ent.max_mana,
            stamina=ent.stamina,
            max_stamina=ent.max_stamina,
            stat_modifier_strength=ent.stat_modifier_strength,
            stat_modifier_dexterity=ent.stat_modifier_dexterity,
            stat_modifier_intelligence=ent.stat_modifier_intelligence,
            stat_modifier_wisdom=ent.stat_modifier_wisdom,
            stat_modifier_charisma=ent.stat_modifier_charisma,
            stat_modifier_armor_class=ent.stat_modifier_armor_class,
            is_attackable=ent.is_attackable,
            is_killable=ent.is_killable,
            inventory=deepcopy(ent.inventory),
            metadata_json=deepcopy(ent.metadata_json),
        )
        db.add(new_ent)
