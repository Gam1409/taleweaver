"""Restore a session bundle, including avatar, inventory and state snapshot."""

from copy import deepcopy

from backend.core.game_modes import normalize_vn_template
from backend.engine.import_build_session_template import build_session_template
from backend.engine.item_logic import normalize_equipment_keys
from backend.engine.world_generator import WorldGenerator
from backend.models.avatar import Avatar
from backend.models.game_session import GameSession
from backend.models.session_state import SessionState
from backend.utils.text_utils import generate_session_id


async def restore_session_bundle(db, payload, user, origin_id):
    data = payload
    old_adv = data["adventure"]

    new_template = build_session_template(data, user, origin_id)

    normalize_vn_template(new_template)
    db.add(new_template)
    await db.flush()

    await WorldGenerator.apply_manifest(db, new_template.id, data, user=user)

    # Imported session bundles should not enter generation polling state.
    new_template.is_ready = True
    new_template.creation_status = "Ready"
    new_template.creation_error = None

    old_state = data.get("game_state") or data.get("session_state")
    old_avatar = data.get("avatar")
    if old_state and old_avatar:
        new_avatar = Avatar(
            user_id=user.id,
            template_id=new_template.id,
            name=old_avatar["name"],
            role=old_avatar.get("role"),
            description=old_avatar.get("description"),
            profile_image=old_avatar.get("profile_image"),
            hp=old_avatar["hp"],
            max_hp=old_avatar.get("max_hp", old_avatar["hp"]),
            stamina=old_avatar["stamina"],
            max_stamina=old_avatar.get("max_stamina", old_avatar["stamina"]),
            mana=old_avatar["mana"],
            max_mana=old_avatar.get("max_mana", old_avatar["mana"]),
            strength=old_avatar.get("strength", 10),
            dexterity=old_avatar.get("dexterity", 10),
            intelligence=old_avatar.get("intelligence", 10),
            wisdom=old_avatar.get("wisdom", 10),
            charisma=old_avatar.get("charisma", 10),
            armor_class=old_avatar.get("armor_class", 10),
            exp=old_avatar.get("exp", 0),
            goal=old_avatar.get("goal", ""),
            character=old_avatar.get("character", ""),
            visual_profile=deepcopy(old_avatar.get("visual_profile")),
            stats=old_avatar["stats"],
            inventory=old_avatar["inventory"],
            equipment=normalize_equipment_keys(old_avatar.get("equipment")),
            status_effects=old_avatar.get("status_effects", []),
        )
        db.add(new_avatar)
        await db.flush()

        new_sess = GameSession(
            id=generate_session_id(new_template.title or old_adv.get("title") or "session"),
            user_id=user.id,
            avatar_id=new_avatar.id,
            template_id=new_template.id,
            adventure_title=new_template.title,
            adventure_image_url=new_template.image_url,
        )
        db.add(new_sess)
        await db.flush()

        restored_entity_states = old_state.get("entity_states", {})
        if not isinstance(restored_entity_states, dict):
            restored_entity_states = {}
        restored_entity_states = deepcopy(restored_entity_states)
        restored_entity_states.setdefault(
            "__manifest_snapshot__",
            {
                "adventure": {
                    "id": new_template.id,
                    "title": new_template.title,
                    "version": new_template.version,
                    "image_url": new_template.image_url,
                    "strict_rules": new_template.strict_rules,
                    "rule_enforcement_mode": new_template.rule_enforcement_mode,
                    "time_per_turn": new_template.time_per_turn,
                    "clock_enabled": new_template.clock_enabled,
                    "time_system": new_template.time_system,
                    "time_config": deepcopy(new_template.time_config or {}),
                    "selected_tone": deepcopy(new_template.selected_tone or {}),
                    "selected_image_styles": deepcopy(new_template.selected_image_styles or []),
                    "quests": deepcopy(new_template.quests or []),
                    "awards": deepcopy(new_template.awards or []),
                    "plot": new_template.plot,
                    "rules": new_template.rules,
                    "intro_text": new_template.intro_text,
                    "walkthrough": new_template.walkthrough,
                    "completed_condition": new_template.completed_condition,
                    "gameover_condition": new_template.gameover_condition,
                    "tts_director_notes": new_template.tts_director_notes,
                    "original_prompt": new_template.original_prompt,
                    "allow_dynamic_items": new_template.allow_dynamic_items,
                    "is_adventure_generator": new_template.is_adventure_generator,
                },
                "original_manifest": deepcopy(new_template.original_manifest or {}),
            },
        )

        db.add(
            SessionState(
                session_id=new_sess.id,
                current_scene_id=old_state.get("scene_id")
                or old_state.get("current_scene_id")
                or "START",
                in_game_time=old_state.get("in_game_time", 0),
                inventory=old_state.get("inventory", []),
                entity_states=restored_entity_states,
                exit_states=old_state.get("exit_states", {}),
                discovered_scenes=old_state.get("discovered_scenes", []),
            )
        )

    await db.commit()
    # Ensure thumbnails are generated for imported assets
    from backend.engine.media_engine import MediaEngine

    await MediaEngine.ensure_thumbnails(new_template.id)
    return True
