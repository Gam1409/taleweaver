"""Optional post-narration reconciliation, isolated from mechanical mutations."""

import asyncio
import json
import logging
from typing import Any

from backend.core.llm_deadlines import role_timeout
from backend.core.llm_router import GameMasterLLM
from backend.engine.scene_staging.schema import INSTRUCTIONS, SceneExtraction
from backend.engine.scene_staging.state import KEY, MAX_CAST, digest, project, reconcile
from backend.engine.turn_replay.transactions import release_for_model
from backend.engine.visual_novel.config import read_settings

logger = logging.getLogger(__name__)
MAX_NARRATION = 16000


async def reconcile_narration(manager: Any, narration: str, *, completed: bool) -> None:
    if not read_settings(manager.state).scene_staging:
        return
    state = manager.state
    result = {
        "scene_id": state.current_scene_id,
        "status": "unconfirmed",
        "source_hash": digest(narration),
        "actors": {},
    }
    if not completed or not narration.strip() or len(narration) > MAX_NARRATION:
        state.entity_states = {**(state.entity_states or {}), KEY: result}
        return
    from backend.api.routes.adventures.logic import AdventureLogic

    entities = await AdventureLogic.build_session_entities(manager.db, state)
    cast = [{"id": manager.avatar.id, "name": manager.avatar.name}]
    cast.extend(
        {
            "id": entity["id"],
            "name": entity.get("name"),
            "position": entity.get("spatial_position"),
        }
        for entity in entities
        if entity.get("entity_type") == "NPC" and not entity.get("is_defeated")
    )
    if len(cast) > MAX_CAST:
        state.entity_states = {**(state.entity_states or {}), KEY: result}
        return  # Never silently drop a character or truncate the completed narrative.
    payload = json.dumps(
        {
            "scene_id": state.current_scene_id,
            "present_cast": cast,
            "previous_staging": project(state, cast),
            "current_narration": narration,
        },
        ensure_ascii=False,
    )
    # The turn's mutation lease and recovery record protect this short commit.
    await release_for_model(manager)
    try:
        llm = GameMasterLLM.for_role(manager.user, "small")
        response = await asyncio.wait_for(
            llm.aexecute_complex_task(
                INSTRUCTIONS,
                payload,
                SceneExtraction,
                llm.model,
                operation="scene_staging",
                phase="reconciliation",
                game_id=manager.game_id,
            ),
            timeout=role_timeout(manager.user, "small"),
        )
        result = reconcile(state, cast, narration, SceneExtraction.model_validate(response))
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("Scene staging reconciliation failed for session %s", manager.game_id)
    finally:
        state.entity_states = {**(state.entity_states or {}), KEY: result}
