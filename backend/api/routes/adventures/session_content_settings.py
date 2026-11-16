"""Owner-scoped preferences for future responses in an existing session."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import Text, cast, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.routes.adventures.session_mutations import session_mutation_lease
from backend.core.auth import get_current_user
from backend.core.database import get_db
from backend.engine.session_content_settings import (
    ContentPreferences,
    ContentPreferencesUpdate,
    ContentSettingsConflictError,
    read_preferences,
    save_preferences,
)
from backend.models.game_session import GameSession
from backend.models.session_state import SessionState
from backend.models.user import User

router = APIRouter(tags=["Session settings"], dependencies=[Depends(session_mutation_lease)])


async def _owned(db: AsyncSession, game_id: str, user: User) -> tuple[SessionState, str | None]:
    row = (
        await db.execute(
            select(SessionState, cast(SessionState.entity_states, Text).label("state_json"))
            .join(GameSession, GameSession.id == SessionState.session_id)
            .where(GameSession.id == game_id, GameSession.user_id == user.id)
            .execution_options(populate_existing=True)
        )
    ).first()
    if row is None:
        raise HTTPException(404, "Session not found.")
    return row[0], row[1]


@router.get("/{game_id}/content-settings", response_model=ContentPreferences)
async def read(
    game_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ContentPreferences:
    state, _ = await _owned(db, game_id, user)
    try:
        return read_preferences(state.entity_states)
    except ContentSettingsConflictError as exc:
        raise HTTPException(409, str(exc)) from None


@router.patch("/{game_id}/content-settings", response_model=ContentPreferences)
async def patch(
    game_id: str,
    payload: ContentPreferencesUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ContentPreferences:
    state, before = await _owned(db, game_id, user)
    try:
        return await save_preferences(db, state, before, payload)
    except ContentSettingsConflictError as exc:
        await db.rollback()
        raise HTTPException(409, str(exc)) from None
