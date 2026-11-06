"""Two independent session opt-ins for narrator-authored portrait presentation."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import Text, cast, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.routes.adventures.session_mutations import session_mutation_lease
from backend.core.auth import get_current_user
from backend.core.database import get_db
from backend.core.npc_presentation import PortraitPreferences, PreferencesUpdate
from backend.engine.npc_presentation.settings import PreferencesConflictError, read, save
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


@router.get("/{game_id}/portrait-settings", response_model=PortraitPreferences)
async def get_settings(
    game_id: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
) -> PortraitPreferences:
    state, _ = await _owned(db, game_id, user)
    try:
        return read(state.entity_states)
    except PreferencesConflictError as exc:
        raise HTTPException(409, str(exc)) from None


@router.patch("/{game_id}/portrait-settings", response_model=PortraitPreferences)
async def update_settings(
    game_id: str,
    payload: PreferencesUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> PortraitPreferences:
    state, before = await _owned(db, game_id, user)
    try:
        return await save(db, state, before, payload)
    except PreferencesConflictError as exc:
        await db.rollback()
        raise HTTPException(409, str(exc)) from None
