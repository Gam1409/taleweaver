"""Optional post-narration reconciliation, isolated from mechanical mutations."""

import asyncio
import json
import logging
from typing import Any

from backend.core.llm_deadlines import role_timeout
from backend.core.llm_router import GameMasterLLM
from backend.core.state_rejection_trace import reject
from backend.engine.clothing.visuals import session_objects
from backend.engine.narrated_items import evidence, reference_schema, response_sections
from backend.engine.scene_staging import props
from backend.engine.scene_staging.proposals import StagingProposal
from backend.engine.scene_staging.schema import INSTRUCTIONS
from backend.engine.scene_staging.shared import apply_extraction, consume
from backend.engine.scene_staging.state import KEY, digest, project
from backend.engine.turn_replay.transactions import release_for_model
from backend.engine.visual_novel.config import read_settings

logger = logging.getLogger(__name__)
MAX_NARRATION = 16000
MAX_CONTEXT = 64000


async def reconcile_narration(manager: Any, narration: str, *, completed: bool) -> None:
    if not read_settings(manager.state).scene_staging:
        return
    if consume(manager, narration, completed=completed):
        return
    state = manager.state
    result = {
        "scene_id": state.current_scene_id,
        "status": "unconfirmed",
        "source_hash": digest(narration),
        "actors": {},
    }
    if not completed or not narration.strip() or len(narration) > MAX_NARRATION:
        reject(
            "scene_staging",
            "source_unavailable",
            "Completed narration was unavailable or exceeded the staging limit.",
            completed=completed,
            narration=narration,
            narration_characters=len(narration),
            limit=MAX_NARRATION,
        )
        state.entity_states = {**(state.entity_states or {}), KEY: result}
        props.invalidate(state)
        return
    from backend.engine.gameplay.world import AdventureLogic

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
    items = [item for item in valid_items if item["owner_id"] in present or item.get("scene_bound")]
    catalog = evidence.Catalog(
        narration,
        scope=f"{state.session_id}:{getattr(manager, '_vn_player_message_id', '')}:{state.current_scene_id}",
    )
    payload = json.dumps(
        {
            "scene_id": state.current_scene_id,
            "present_cast": cast,
            "owned_items": items,
            "previous_staging": project(state, cast),
            "current_narration": catalog.narration_passages,
        },
        ensure_ascii=False,
    )
    if len(payload) > MAX_CONTEXT:
        reject(
            "scene_staging",
            "context_limit",
            "Staging context exceeds the text budget.",
            context_characters=len(payload),
            context=payload,
            limit=MAX_CONTEXT,
            cast=cast,
        )
        result.update(reason="Staging context exceeds the text budget.", cast_size=len(cast))
        state.entity_states = {**(state.entity_states or {}), KEY: result}
        props.invalidate(state)
        return
    # The turn's mutation lease and recovery record protect this short commit.
    await release_for_model(manager)
    applied = False
    try:
        llm = GameMasterLLM.for_role(manager.user, "small")
        response = await asyncio.wait_for(
            llm.aexecute_complex_task(
                INSTRUCTIONS,
                payload,
                StagingProposal,
                llm.model,
                operation="scene_staging",
                phase="reconciliation",
                response_schema=reference_schema.build(StagingProposal, catalog, complete=True),
                game_id=manager.game_id,
            ),
            timeout=role_timeout(manager.user, "small"),
        )
        apply_extraction(
            manager,
            narration,
            cast,
            rows,
            evidence.bind_staging(response, catalog),
            unconfirmed_sections=response_sections.missing_staging(response),
        )
        applied = True
    except asyncio.CancelledError:
        raise
    except Exception as error:
        reject(
            "scene_staging",
            "extraction_failed",
            "Scene staging extraction could not complete.",
            error_type=type(error).__name__,
            narration=narration,
        )
        logger.exception("Scene staging reconciliation failed for session %s", manager.game_id)
    finally:
        if not applied:
            props.invalidate(state)
            state.entity_states = {**(state.entity_states or {}), KEY: result}
