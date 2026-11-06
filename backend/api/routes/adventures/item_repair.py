"""Owner-only debug previews and explicit application for session item repairs."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.routes.adventures.editing.generation_errors import generation_error
from backend.api.routes.adventures.session_mutations import session_mutation_lease
from backend.core.auth import get_current_user
from backend.core.config import settings
from backend.core.database import get_db
from backend.engine import item_repair
from backend.engine.item_repair_contracts import RepairApply, RepairRequest
from backend.engine.item_repair_store import ItemContext, apply
from backend.models.avatar import Avatar
from backend.models.game_session import GameSession
from backend.models.session_state import SessionState
from backend.models.turn_replay import TurnReplay
from backend.models.user import User
from backend.models.world_entity import WorldEntity

router = APIRouter(tags=["Item repair"])


async def _context(db: AsyncSession, game_id: str, item_id: str, user: User) -> ItemContext:
    state = await db.scalar(
        select(SessionState)
        .join(GameSession, GameSession.id == SessionState.session_id)
        .where(
            GameSession.id == game_id,
            GameSession.user_id == user.id,
        )
        .execution_options(populate_existing=True)
    )
    if state is None:
        raise HTTPException(404, "Session not found.")
    if not (settings.TALEWEAVER_DEBUG_ENABLED or state.is_debug_enabled):
        raise HTTPException(403, "Enable debug mode before repairing session items.")
    avatar = await db.get(Avatar, state.avatar_id, populate_existing=True)
    if avatar is None or avatar.user_id != user.id:
        raise HTTPException(404, "Session character not found.")
    entities = list(
        await db.scalars(
            select(WorldEntity)
            .where(WorldEntity.session_id == game_id)
            .execution_options(populate_existing=True)
        )
    )
    context = ItemContext(state, avatar, entities, item_id)
    context.read()
    return context


@router.get("/{game_id}/items/{item_id}/repair")
async def read(
    game_id: str,
    item_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    context = await _context(db, game_id, item_id, user)
    return {"item": context.read(), "before_hash": context.fingerprint()}


@router.post("/{game_id}/items/{item_id}/repair/preview")
async def preview(
    game_id: str,
    item_id: str,
    payload: RepairRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    context = await _context(db, game_id, item_id, user)
    context.check(payload.before_hash)
    item = context.read()
    await db.commit()
    try:
        draft = await item_repair.propose(user, item, payload.instruction, game_id)
    except Exception as exc:
        raise generation_error(exc) from exc
    return {"values": draft.model_dump(mode="json"), "before_hash": payload.before_hash}


@router.post("/{game_id}/items/{item_id}/repair/image")
async def image(
    game_id: str,
    item_id: str,
    payload: RepairRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    context = await _context(db, game_id, item_id, user)
    context.check(payload.before_hash)
    try:
        image_url = await item_repair.generate_image(db, context, user)
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        error = generation_error(exc)
        if error.status_code == 502:
            error.detail = "Item image generation failed. The previous image was kept; check image-provider diagnostics."
        raise error from exc
    return {"image_url": image_url, "before_hash": payload.before_hash}


@router.post(
    "/{game_id}/items/{item_id}/repair/apply", dependencies=[Depends(session_mutation_lease)]
)
async def commit(
    game_id: str,
    item_id: str,
    payload: RepairApply,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    context = await _context(db, game_id, item_id, user)
    context.check(payload.before_hash)
    replay = await db.get(TurnReplay, game_id, populate_existing=True)
    if replay and replay.status in {"pending", "replaying", "executing"}:
        raise HTTPException(409, "Finish or recover the outstanding turn before editing items.")
    item_repair.validate_technical(context, payload)
    previous = context.read()
    try:
        item = apply(context, payload)
    except ValueError as exc:
        raise HTTPException(
            422, "The repair conflicts with existing clothing references. " + str(exc)
        ) from exc
    replay_invalidated = bool(replay and replay.status == "ready" and item != previous)
    if replay_invalidated and replay:
        # Replaying a pre-edit turn would silently restore the old item. Do not
        # transplant a current repair into historical snapshots or their evidence.
        replay.status = "edited"
    await db.commit()
    return {
        "item": item,
        "before_hash": context.fingerprint(),
        "replay_invalidated": replay_invalidated,
    }
