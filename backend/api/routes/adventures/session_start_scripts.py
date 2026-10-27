import json
import logging
from copy import deepcopy

from backend.core.config import settings
from backend.core.game_modes import is_vn
from backend.engine.scripting.context import GameContext
from backend.engine.scripting.runner import ScriptRunner
from backend.models.base import utc_now
from backend.models.chat import ChatMessage

logger = logging.getLogger(__name__)


def run_adventure_initialization(
    adventure, template_entities, avatar, first_scene_id, initial_entity_states
):
    # Execute adventure initialization script and on_init triggers if configured
    manifest = getattr(adventure, "original_manifest", None) or {}
    adv_scripts = manifest.get("scripts", [])
    adv_init_script = manifest.get("init_script") or getattr(adventure, "init_script", None)
    init_narrative_messages: list[str] = []

    if not is_vn(adventure) and (
        adv_init_script
        or any(isinstance(s, dict) and s.get("trigger") == "on_init" for s in adv_scripts)
    ):
        entities_map = {ent.id: ent.__dict__.copy() for ent in template_entities if ent.id}
        avatar_dict = {
            "name": avatar.name,
            "hp": avatar.hp,
            "mana": avatar.mana,
            "stamina": avatar.stamina,
            "inventory": list(avatar.inventory or []),
            "status_effects": list(avatar.status_effects or []),
        }
        init_context = GameContext(
            avatar_data=avatar_dict,
            current_scene_id=first_scene_id,
            entities=entities_map,
            exit_states={},
            quests=deepcopy(adventure.quests or []),
            script_vars={},
            in_game_time=0,
            story_flags={},
            is_debug_enabled=bool(settings.TALEWEAVER_DEBUG_ENABLED),
        )
        runner = ScriptRunner(scripts=adv_scripts, init_script=adv_init_script)
        cs = runner.run_init_script(init_context)

        script_vars = dict(cs.var_updates)
        script_vars["__init_script_executed__"] = True
        initial_entity_states["__script_vars__"] = script_vars

        if getattr(cs, "story_flag_updates", None):
            initial_entity_states["__switch_story_flags__"] = dict(cs.story_flag_updates)

        if cs.player_hp_change:
            avatar.hp = max(0, min(avatar.max_hp, avatar.hp + cs.player_hp_change))
        if cs.player_mana_change:
            avatar.mana = max(0, min(avatar.max_mana, avatar.mana + cs.player_mana_change))
        if cs.player_stamina_change:
            avatar.stamina = max(
                0, min(avatar.max_stamina, avatar.stamina + cs.player_stamina_change)
            )

        init_narrative_messages.extend([str(m) for m in cs.narrative_messages])

    return init_narrative_messages


async def add_initial_session_messages(db, adventure, new_session, init_narrative_messages):
    # Add Creator, Copyright, License details as a dedicated license_info message
    # Pin created_at explicitly so the license_info row sorts before intro_text
    if adventure.creator or adventure.copyright or adventure.license or adventure.license_url:
        license_payload = {
            "creator": adventure.creator,
            "copyright": adventure.copyright,
            "license": adventure.license,
            "license_url": adventure.license_url,
        }
        license_msg = ChatMessage(
            session_id=new_session.id,
            role="license_info",
            content=json.dumps(license_payload),
        )
        license_msg.created_at = utc_now()
        db.add(license_msg)
        await db.flush()  # Ensure license_info gets an id and committed timestamp

    intro_text = (adventure.intro_text or "").strip()
    if intro_text:
        db.add(ChatMessage(session_id=new_session.id, role="system", content=intro_text))

    for msg in init_narrative_messages:
        db.add(ChatMessage(session_id=new_session.id, role="system", content=msg))
