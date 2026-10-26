"""Pin legacy template-scoped mutations to concrete sessions before writing."""

from contextlib import ExitStack

from fastapi import HTTPException
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.engine.memory_rag.lifecycle import purge_session_memory
from backend.engine.visual_novel.concurrency import (
    BUSY_DETAIL,
    SessionBusyError,
    session_write_lease,
)
from backend.models.adventure_template import AdventureTemplate
from backend.models.chat import ChatMessage
from backend.models.game_session import GameSession
from backend.models.session_checkpoint import SessionCheckpoint
from backend.models.session_state import SessionState
from backend.models.world_entity import WorldEntity, WorldExit, WorldScene
from backend.models.world_map import WorldMap


async def _target(db: AsyncSession, template_id: str, user_id: str, status: str) -> str:
    identifier = await db.scalar(
        select(GameSession.id)
        .where(
            GameSession.template_id == template_id,
            GameSession.user_id == user_id,
            GameSession.status == status,
        )
        .order_by(GameSession.created_at.desc(), GameSession.id.desc())
        .limit(1)
    )
    if identifier is None:
        raise HTTPException(404, f"No {status} session found for this adventure.")
    return identifier


async def _current(db: AsyncSession, identifier: str, user_id: str, status: str) -> GameSession:
    session = await db.get(GameSession, identifier, populate_existing=True)
    if session is None or session.user_id != user_id or session.status != status:
        raise HTTPException(409, "The selected session changed. Refresh and try again.")
    return session


async def update_state(db: AsyncSession, template_id: str, user_id: str, payload: dict) -> dict:
    identifier = await _target(db, template_id, user_id, "active")
    try:
        with session_write_lease(identifier):
            await _current(db, identifier, user_id, "active")
            state = await db.scalar(
                select(SessionState)
                .where(SessionState.session_id == identifier)
                .execution_options(populate_existing=True)
            )
            if state is None:
                raise HTTPException(404, "Session state not found.")
            for key, attribute in (
                ("scene_id", "current_scene_id"),
                ("in_game_time", "in_game_time"),
            ):
                if key in payload:
                    setattr(state, attribute, payload[key])
            await db.commit()
            return {
                "scene_id": state.current_scene_id,
                "in_game_time": state.in_game_time or 0,
                "is_paused": False,
                "session_id": identifier,
            }
    except SessionBusyError:
        raise HTTPException(409, BUSY_DETAIL) from None


async def change_status(
    db: AsyncSession, template_id: str, user_id: str, previous: str, following: str
) -> dict:
    identifier = await _target(db, template_id, user_id, previous)
    try:
        with session_write_lease(identifier):
            session = await _current(db, identifier, user_id, previous)
            session.status = following
            await db.commit()
    except SessionBusyError:
        raise HTTPException(409, BUSY_DETAIL) from None
    return {"status": following, "game_id": identifier}


async def reset_sessions(db: AsyncSession, template_id: str, user_id: str) -> dict:
    template = await db.get(AdventureTemplate, template_id)
    if template is None or template.owner_id != user_id:
        raise HTTPException(404, "Adventure template not found.")
    targets = (
        await db.execute(
            select(GameSession.id, GameSession.user_id).where(
                GameSession.template_id == template_id
            )
        )
    ).all()
    identifiers = [identifier for identifier, _ in targets]
    try:
        with ExitStack() as leases:
            for identifier in sorted(identifiers):
                leases.enter_context(session_write_lease(identifier))
            await _purge_captured_sessions(db, targets, identifiers)
            await db.commit()
    except SessionBusyError:
        raise HTTPException(409, BUSY_DETAIL) from None
    return {"status": "success"}


async def _purge_captured_sessions(db: AsyncSession, targets: list, identifiers: list[str]) -> None:
    """Fence derived data first; new sessions created after selection are untouched.

    Template assets and avatars intentionally survive this legacy reset operation.
    """
    for identifier, owner_id in targets:
        await purge_session_memory(db, owner_id, identifier)
    for model in (
        SessionCheckpoint,
        ChatMessage,
        SessionState,
        WorldEntity,
        WorldScene,
        WorldExit,
        WorldMap,
    ):
        await db.execute(delete(model).where(model.session_id.in_(identifiers)))
    await db.execute(
        update(GameSession)
        .where(GameSession.copied_from_id.in_(identifiers))
        .values(copied_from_id=None)
    )
    await db.execute(delete(GameSession).where(GameSession.id.in_(identifiers)))
