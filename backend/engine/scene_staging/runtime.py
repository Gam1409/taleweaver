"""Optional post-narration reconciliation, isolated from mechanical mutations."""

import asyncio
import json
import logging
from typing import Any

from backend.core.llm_deadlines import role_timeout
from backend.core.llm_router import GameMasterLLM
from backend.core.reliability_metrics import record_staging
from backend.engine.clothing.visuals import session_objects
from backend.engine.scene_staging import props
from backend.engine.scene_staging.schema import INSTRUCTIONS, SceneExtraction
from backend.engine.scene_staging.state import KEY, digest, project, reconcile
from backend.engine.turn_replay.transactions import release_for_model
from backend.engine.visual_novel.config import read_settings

logger = logging.getLogger(__name__)
MAX_NARRATION = 16000
MAX_CONTEXT = 64000


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
        props.invalidate(state)
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
    rows = await session_objects(manager.db, state.session_id)
    valid_items = props.candidates(
        manager.avatar, rows, state, {row.id for row in rows if row.entity_type == "NPC"}
    )
    present = {person["id"] for person in cast}
    items = [item for item in valid_items if item["owner_id"] in present]
    payload = json.dumps(
        {
            "scene_id": state.current_scene_id,
            "present_cast": cast,
            "owned_items": items,
            "previous_staging": project(state, cast),
            "current_narration": narration,
        },
        ensure_ascii=False,
    )
    if len(payload) > MAX_CONTEXT:
        result.update(reason="Staging context exceeds the text budget.", cast_size=len(cast))
        state.entity_states = {**(state.entity_states or {}), KEY: result}
        props.invalidate(state)
        return
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
        extraction = SceneExtraction.model_validate(response)
        result = reconcile(state, cast, narration, extraction)
        record_staging(result, len(extraction.changes))
        props.reconcile(state, narration, extraction.props, items, valid_items=valid_items)
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("Scene staging reconciliation failed for session %s", manager.game_id)
    finally:
        if result.get("status") != "ready":
            props.invalidate(state)
        state.entity_states = {**(state.entity_states or {}), KEY: result}
