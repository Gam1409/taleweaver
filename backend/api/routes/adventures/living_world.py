"""Owner-scoped experimental controls; private event details are administrator-only."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.routes.adventures.session_mutations import session_mutation_lease
from backend.core.auth import get_current_user
from backend.core.database import get_db
from backend.engine.living_world import presence, runner
from backend.engine.living_world.schema import (
    Command,
    Event,
    PresenceUpdate,
    SettingsUpdate,
    Simulation,
)
from backend.engine.living_world.state import load, public_status, reconcile, save
from backend.models.game_session import GameSession
from backend.models.session_state import SessionState
from backend.models.user import User

router = APIRouter(tags=["Living World"])
mutation = [Depends(session_mutation_lease)]


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
        raise HTTPException(409, "Living World changed. Reload its status before retrying.")


async def game_row(db: AsyncSession, game_id: str) -> GameSession:
    game = await db.get(GameSession, game_id)
    if game is None:
        raise HTTPException(404, "Session not found.")
    return game


@router.get("/{game_id}/living-world")
async def status(
    game_id: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
) -> dict:
    state = await owned(db, game_id, user)
    simulation = read_simulation(state)
    game = await game_row(db, game_id)
    if simulation.settings.living_world_enabled:
        reconcile(simulation, int(state.in_game_time or 0), game.living_world_presence)
    result = public_status(simulation)
    if result["status"] == "RUNNING" and game_id not in runner.running:
        result["status"] = "PARTIAL"
    return result


@router.patch("/{game_id}/living-world", dependencies=mutation)
async def configure(
    game_id: str,
    payload: SettingsUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    state = await owned(db, game_id, user)
    simulation = read_simulation(state)
    check_revision(simulation, payload.expected_revision)
    game = await game_row(db, game_id)
    reconcile(simulation, int(state.in_game_time or 0), game.living_world_presence)
    if simulation.target > simulation.cursor and payload.settings.mode != simulation.settings.mode:
        raise HTTPException(409, "Finish pending catch-up before changing the time mode.")
    if (
        payload.settings.living_world_enabled != simulation.settings.living_world_enabled
        or payload.settings.mode != simulation.settings.mode
    ):
        game.living_world_presence = None
        simulation.offline_total_seen = 0
    simulation.settings = payload.settings
    if not simulation.settings.living_world_enabled or simulation.target == simulation.cursor:
        simulation.status = "PAUSED"
    save(state, simulation)
    await db.commit()
    return public_status(simulation)


@router.post("/{game_id}/living-world/presence")
async def heartbeat(
    game_id: str,
    payload: PresenceUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    state = await owned(db, game_id, user)
    if read_simulation(state).settings.living_world_enabled:
        await presence.record(db, game_id, user.id, payload.client_id, payload.active)
    return {"ok": True}


@router.post("/{game_id}/living-world/resume", dependencies=mutation)
async def resume(
    game_id: str,
    payload: Command,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    state = await owned(db, game_id, user)
    simulation = read_simulation(state)
    check_revision(simulation, payload.expected_revision)
    if not simulation.settings.living_world_enabled:
        raise HTTPException(409, "Enable Living World first.")
    game = await game_row(db, game_id)
    reconcile(simulation, int(state.in_game_time or 0), game.living_world_presence)
    save(state, simulation)
    await db.commit()
    await runner.run(db, state, simulation)
    return public_status(simulation)


@router.post("/{game_id}/living-world/stop")
async def stop(
    game_id: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
) -> dict:
    await owned(db, game_id, user)
    request = runner.running.get(game_id)
    if request is not None:
        request.set()
    return {"stop_requested": request is not None}


@router.get("/{game_id}/living-world/events")
async def events(
    game_id: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
) -> dict:
    state = await owned(db, game_id, user)
    if user.role != "admin":
        raise HTTPException(
            403, "Administrator access is required for the private simulation journal."
        )
    simulation = read_simulation(state)
    return {
        "timeline": simulation.timeline,
        "events": [event.model_dump() for event in simulation.events],
    }


@router.post("/{game_id}/living-world/events", dependencies=mutation)
async def schedule(
    game_id: str,
    event: Event,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    state = await owned(db, game_id, user)
    if user.role != "admin":
        raise HTTPException(
            403, "Administrator access is required to schedule experimental events."
        )
    simulation = read_simulation(state)
    existing = next((item for item in simulation.events if item.event_id == event.event_id), None)
    if existing is not None:
        raise HTTPException(409, "This event ID already exists in the timeline.")
    known = {item.event_id: item.due for item in simulation.events}
    if (
        len(simulation.events) >= 512
        or event.due < simulation.cursor
        or any(key not in known or known[key] > event.due for key in event.dependencies)
    ):
        raise HTTPException(422, "Invalid event time, prerequisites, or queue capacity.")
    if (
        event.status != "PLANNED"
        or event.result
        or event.observed_by_player
        or event.committed_at is not None
    ):
        raise HTTPException(422, "Only unexecuted event proposals can be scheduled.")
    simulation.events.append(event)
    save(state, simulation)
    await db.commit()
    return public_status(simulation)
