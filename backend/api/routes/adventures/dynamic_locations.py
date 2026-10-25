"""Owner-only policy and image status for session-local exploration."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.auth import get_current_user
from backend.core.database import get_db
from backend.engine.dynamic_locations import images
from backend.engine.dynamic_locations.schema import LocationPolicy, policy, registry, save_registry
from backend.models.game_session import GameSession
from backend.models.session_state import SessionState
from backend.models.user import User
from backend.models.world_entity import WorldScene

router = APIRouter(tags=["Dynamic locations"])


async def _owned(db, game_id, user):
    state = await db.scalar(
        select(SessionState)
        .join(GameSession)
        .where(
            GameSession.id == game_id,
            GameSession.user_id == user.id,
        )
    )
    if state is None:
        raise HTTPException(404, "Session not found.")
    return state


@router.get("/{game_id}/dynamic-locations")
async def read(
    game_id: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    state = await _owned(db, game_id, user)
    data = registry(state)
    scene = await db.scalar(
        select(WorldScene).where(
            WorldScene.session_id == game_id,
            WorldScene.id == state.current_scene_id,
        )
    )
    dynamic = state.current_scene_id in data.get("places", {})
    return {
        "policy": policy(state).model_dump(),
        "count": len(data.get("places", {})),
        "inferred_scale": data.get("inferred_scale"),
        "scene_id": state.current_scene_id,
        "dynamic": dynamic,
        "image_url": scene.image_url if scene else None,
        "image_status": images.status(
            game_id, state.current_scene_id, scene.image_url if scene else None
        )
        if dynamic
        else None,
    }


@router.patch("/{game_id}/dynamic-locations")
async def update(
    game_id: str,
    payload: LocationPolicy,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    state = await _owned(db, game_id, user)
    save_registry(state, {**registry(state), "policy": payload.model_dump()})
    await db.commit()
    return {"policy": payload.model_dump()}


@router.post("/{game_id}/dynamic-locations/{scene_id}/image")
async def retry(
    game_id: str,
    scene_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    state = await _owned(db, game_id, user)
    if scene_id not in registry(state).get("places", {}):
        raise HTTPException(404, "Dynamic location not found.")
    images.schedule(game_id, scene_id, user.id)
    return {"status": "queued"}
