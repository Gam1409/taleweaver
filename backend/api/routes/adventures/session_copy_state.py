import logging
from copy import deepcopy

from sqlalchemy import select

from backend.engine.living_world.state import fork as fork_simulation
from backend.models.session_state import SessionState

logger = logging.getLogger(__name__)


async def clone_saved_session_state(
    db, original_session, copied_session, current_user, cloned_avatar, asset_copy_cache
):
    from .sessions import _rewrite_asset_snapshot_urls

    # 5. Clone SessionState
    state_res = await db.execute(
        select(SessionState).where(SessionState.session_id == original_session.id)
    )
    original_state = state_res.scalars().first()
    cloned_state = None
    if original_state:
        entity_states = deepcopy(original_state.entity_states)
        if isinstance(entity_states, dict):
            raw_snapshot = entity_states.get("__asset_snapshot__")
            if isinstance(raw_snapshot, dict):
                entity_states["__asset_snapshot__"] = _rewrite_asset_snapshot_urls(
                    copied_session.id,
                    raw_snapshot,
                    asset_copy_cache,
                )

        cloned_state = SessionState(
            session_id=copied_session.id,
            user_id=current_user.id,
            template_id=original_state.template_id,
            avatar_id=cloned_avatar.id,
            current_scene_id=original_state.current_scene_id,
            in_game_time=original_state.in_game_time,
            max_memory_turns=getattr(original_state, "max_memory_turns", 10) or 10,
            time_system=original_state.time_system,
            time_config=deepcopy(original_state.time_config),
            inventory=deepcopy(original_state.inventory),
            entity_states=entity_states,
            living_world=fork_simulation(original_state.living_world),
            exit_states=deepcopy(original_state.exit_states),
            discovered_scenes=deepcopy(original_state.discovered_scenes),
            quests=deepcopy(original_state.quests),
            start_datetime=original_state.start_datetime,
            plot=original_state.plot,
            rules=original_state.rules,
            walkthrough=original_state.walkthrough,
            completed_condition=original_state.completed_condition,
            gameover_condition=original_state.gameover_condition,
            completed_guard_expression=original_state.completed_guard_expression,
            gameover_guard_expression=original_state.gameover_guard_expression,
            tts_director_notes=original_state.tts_director_notes,
            selected_image_styles=deepcopy(original_state.selected_image_styles),
            selected_tone=deepcopy(original_state.selected_tone),
            is_completed=original_state.is_completed,
            is_debug_enabled=original_state.is_debug_enabled,
            is_walkthrough_revealed=original_state.is_walkthrough_revealed,
            allow_dynamic_items=original_state.allow_dynamic_items,
        )
        db.add(cloned_state)

    return original_state, cloned_state
