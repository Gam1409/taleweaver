"""Change a running session's image preset source without recreating the session."""

from copy import deepcopy
from types import SimpleNamespace

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import Text, cast, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.routes.adventures.session_content_settings import _owned
from backend.api.routes.adventures.session_mutations import session_mutation_lease
from backend.api.routes.adventures.visual_presets import StoryPresets
from backend.core.auth import get_current_user
from backend.core.comfyui_presets import normalize_comfy_presets
from backend.core.database import get_db
from backend.engine.story_visual_presets import story_t2i
from backend.models.session_state import SessionState
from backend.models.turn_replay import TurnReplay
from backend.models.user import User

router = APIRouter(dependencies=[Depends(session_mutation_lease)])


def preferences(states: dict) -> StoryPresets:
    manifest = (states.get("__manifest_snapshot__") or {}).get("original_manifest") or {}
    return StoryPresets(
        source=manifest.get("visual_preset_source", "saved"),
        selection=manifest.get("visual_presets") or {},
    )


def replace(states: dict, payload: StoryPresets) -> dict:
    result = deepcopy(states)
    snapshot = result.get("__manifest_snapshot__")
    if not isinstance(snapshot, dict) or not isinstance(snapshot.get("original_manifest"), dict):
        raise HTTPException(409, "The saved adventure manifest is unavailable.")
    snapshot["original_manifest"].update(
        visual_preset_source=payload.source, visual_presets=payload.selection
    )
    return result


@router.get("/{game_id}/session-visual-presets")
async def read(
    game_id: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
) -> dict:
    state, _ = await _owned(db, game_id, user)
    t2i = normalize_comfy_presets(user.t2i_settings or {})
    return {
        **preferences(state.entity_states or {}).model_dump(),
        "presets": [
            {"id": key, "name": preset["name"]}
            for key, preset in t2i["comfyui_presets"].items()
            if preset.get("generate")
        ],
    }


@router.put("/{game_id}/session-visual-presets")
async def save(
    game_id: str,
    payload: StoryPresets,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    state, before = await _owned(db, game_id, user)
    updated = replace(state.entity_states or {}, payload)
    try:
        story_t2i(
            user.t2i_settings,
            SimpleNamespace(
                original_manifest=updated["__manifest_snapshot__"]["original_manifest"]
            ),
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    replay = await db.scalar(select(TurnReplay).where(TurnReplay.session_id == game_id))
    if replay is not None:
        if replay.status == "replaying":
            raise HTTPException(409, "A turn is being recovered. Try again when it finishes.")
        replay_before = deepcopy(replay.before)
        replay_state = (replay_before or {}).get("state")
        if not isinstance(replay_state, dict):
            raise HTTPException(409, "The turn snapshot is unavailable. Play a new turn first.")
        replay_state["entity_states"] = replace(replay_state.get("entity_states") or {}, payload)
        replay.before = replay_before
    changed = await db.execute(
        update(SessionState)
        .where(SessionState.id == state.id, cast(SessionState.entity_states, Text) == before)
        .values(entity_states=updated)
        .returning(SessionState.id)
        .execution_options(synchronize_session=False)
    )
    if changed.scalar_one_or_none() is None:
        await db.rollback()
        raise HTTPException(409, "Session changed. Reload these settings and try again.")
    await db.commit()
    return payload.model_dump()
