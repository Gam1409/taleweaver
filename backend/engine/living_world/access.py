"""Session ownership and revision checks shared by simulation entrypoints."""

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.engine.living_world.conflicts import SimulationConflict
from backend.engine.living_world.schema import Simulation
from backend.engine.living_world.state import load
from backend.models.game_session import GameSession
from backend.models.session_state import SessionState
from backend.models.user import User


async def owned(db: AsyncSession, game_id: str, user: User) -> SessionState:
    state = await db.scalar(
        select(SessionState)
        .join(GameSession, GameSession.id == SessionState.session_id)
        .where(GameSession.id == game_id, GameSession.user_id == user.id)
    )
    if state is None:
        raise HTTPException(404, "Session not found.")
    return state


def read_simulation(state: SessionState) -> Simulation:
    try:
        return load(state)
    except ValidationError:
        raise HTTPException(
            409, "Living World data could not be validated. Restore a compatible backup."
        ) from None


def check_revision(simulation: Simulation, expected: int) -> None:
    if simulation.revision != expected:
        raise SimulationConflict("Living World changed. Reload its status before retrying.")


async def game_row(db: AsyncSession, game_id: str) -> GameSession:
    game = await db.get(GameSession, game_id)
    if game is None:
        raise HTTPException(404, "Session not found.")
    return game
