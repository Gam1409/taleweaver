"""Keep a foreground turn from overtaking pending offline simulation."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.engine.living_world.state import load, reconcile, save
from backend.engine.visual_novel.concurrency import SessionBusyError
from backend.models.game_session import GameSession
from backend.models.session_state import SessionState


async def check(db: AsyncSession, session_id: str, user_id: str) -> None:
    state = await db.scalar(
        select(SessionState)
        .join(GameSession, GameSession.id == SessionState.session_id)
        .where(GameSession.id == session_id, GameSession.user_id == user_id)
    )
    if state is None or not state.living_world:
        return
    simulation = load(state)
    if not simulation.settings.living_world_enabled:
        return
    game = await db.get(GameSession, session_id)
    if game is None:
        return
    reconcile(simulation, int(state.in_game_time or 0), game.living_world_presence)
    if simulation.settings.mode == "CATCH_UP" and simulation.target > simulation.cursor:
        save(state, simulation)
        await db.commit()
        raise SessionBusyError(
            "Continue Living World catch-up in session settings before playing the next turn."
        )
