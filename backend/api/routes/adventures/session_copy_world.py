import logging
from copy import deepcopy

from sqlalchemy import select

from backend.engine.npc_journal.lifecycle import remap_journal
from backend.models.world_entity import WorldEntity, WorldExit, WorldScene

logger = logging.getLogger(__name__)


async def clone_saved_world(db, original_session, copied_session, asset_copy_cache, message_ids):
    from .sessions import _copy_data_asset_to_session

    # 7. Clone WorldScene
    scenes_res = await db.execute(
        select(WorldScene).where(WorldScene.session_id == original_session.id)
    )
    original_scenes = scenes_res.scalars().all()
    for s in original_scenes:
        copied_scene_image = _copy_data_asset_to_session(
            copied_session.id, "scenes", s.image_url, asset_copy_cache
        )
        cloned_scene = WorldScene(
            id=s.id,
            session_id=copied_session.id,
            template_id=None,
            label=s.label,
            description=s.description,
            image_url=(copied_scene_image or s.image_url),
            decorative_objects=deepcopy(s.decorative_objects),
        )
        db.add(cloned_scene)

    # 8. Clone WorldExit
    exits_res = await db.execute(
        select(WorldExit).where(WorldExit.session_id == original_session.id)
    )
    original_exits = exits_res.scalars().all()
    for e in original_exits:
        cloned_exit = WorldExit(
            session_id=copied_session.id,
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
        db.add(cloned_exit)

    # 9. Clone WorldEntity
    entities_res = await db.execute(
        select(WorldEntity).where(WorldEntity.session_id == original_session.id)
    )
    original_entities = entities_res.scalars().all()
    for ent in original_entities:
        copied_entity_image = _copy_data_asset_to_session(
            copied_session.id, "entities", ent.image_url, asset_copy_cache
        )
        cloned_ent = WorldEntity(
            id=ent.id,
            session_id=copied_session.id,
            template_id=None,
            entity_type=ent.entity_type,
            name=ent.name,
            description=ent.description,
            current_scene_id=ent.current_scene_id,
            spatial_position=ent.spatial_position,
            image_url=(copied_entity_image or ent.image_url),
            item_type=ent.item_type,
            wearable_slots=ent.wearable_slots,
            is_in_inventory=ent.is_in_inventory,
            is_hidden=ent.is_hidden,
            unlock_rule=None,
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
            metadata_json=remap_journal(ent.metadata_json, message_ids),
            voice=ent.voice,
        )
        db.add(cloned_ent)
