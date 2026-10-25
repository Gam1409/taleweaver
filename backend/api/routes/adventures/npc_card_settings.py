"""Owner-only NPC card disclosure preferences with guarded session JSON updates."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import Text, cast, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.auth import get_current_user
from backend.core.database import get_db
from backend.engine.npc_cards.settings import (
    SETTINGS_KEY,
    NpcCardSettings,
    card_insights_enabled,
)
from backend.engine.visual_novel.concurrency import (
    BUSY_DETAIL,
    SessionBusyError,
    session_write_lease,
)
from backend.models.game_session import GameSession
from backend.models.session_state import SessionState
from backend.models.user import User

router = APIRouter(tags=["Session characters"])


async def _owned(db: AsyncSession, game_id: str, user: User) -> tuple[SessionState, str | None]:
    result = await db.execute(
        select(SessionState, cast(SessionState.entity_states, Text).label("state_json"))
        .join(GameSession, GameSession.id == SessionState.session_id)
        .where(GameSession.id == game_id, GameSession.user_id == user.id)
        .execution_options(populate_existing=True)
    )
    row = result.first()
    if row is None:
        raise HTTPException(404, "Session not found.")
    return row[0], row[1]


async def _save(
    db: AsyncSession, state: SessionState, before: str | None, payload: NpcCardSettings
) -> None:
    states = state.entity_states if isinstance(state.entity_states, dict) else {}
    # Compare the stored JSON text, including SQL/JSON null, without relying on
    # database-specific JSON equality or overwriting a concurrent writer's changes.
    result = await db.execute(
        update(SessionState)
        .where(SessionState.id == state.id, cast(SessionState.entity_states, Text) == before)
        .values(entity_states={**states, SETTINGS_KEY: payload.model_dump()})
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        await db.rollback()
        raise HTTPException(409, BUSY_DETAIL)
    await db.commit()


@router.get("/{game_id}/npc-card-settings", response_model=NpcCardSettings)
async def read(
    game_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> NpcCardSettings:
    state, _ = await _owned(db, game_id, user)
    return NpcCardSettings(show_state=card_insights_enabled(state))


@router.patch("/{game_id}/npc-card-settings", response_model=NpcCardSettings)
async def patch(
    game_id: str,
    payload: NpcCardSettings,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> NpcCardSettings:
    # Check ownership before reporting busy state, without loading mutable JSON.
    owned_id = await db.scalar(
        select(GameSession.id).where(GameSession.id == game_id, GameSession.user_id == user.id)
    )
    if owned_id is None:
        raise HTTPException(404, "Session not found.")
    try:
        with session_write_lease(game_id):
            state, before = await _owned(db, game_id, user)
            await _save(db, state, before, payload)
    except SessionBusyError:
        raise HTTPException(409, BUSY_DETAIL) from None
    return payload
