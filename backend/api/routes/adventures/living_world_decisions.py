"""Explicit private decisions with short leases before and after remote inference."""

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.routes.adventures.living_world import check_revision, owned, read_simulation
from backend.core.auth import get_current_user
from backend.core.database import get_db
from backend.core.llm_router import GameMasterLLM
from backend.engine.living_world import deliberation
from backend.engine.living_world.schema import Command
from backend.engine.living_world.state import public_status
from backend.engine.visual_novel.concurrency import SessionBusyError, session_write_lease
from backend.models.user import User

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Living World"])


@router.post("/{game_id}/living-world/deliberate")
async def deliberate(
    game_id: str,
    payload: Command,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    await owned(db, game_id, user)
    if game_id in deliberation.pending:
        raise HTTPException(409, "A private decision is already pending for this session.")
    stop = asyncio.Event()
    deliberation.pending[game_id] = stop
    try:
        llm = GameMasterLLM.for_role(user, "small")
        # Rollback must not expire the router's user/configuration during inference.
        if user in db:
            db.expunge(user)
        await db.rollback()
        with session_write_lease(game_id):
            state = await owned(db, game_id, user)
            simulation = read_simulation(state)
            check_revision(simulation, payload.expected_revision)
            prepared = await deliberation.prepare(db, state, simulation, llm)
        decision = await deliberation.infer_until_stopped(llm, prepared, game_id, stop)
        with session_write_lease(game_id):
            state = await owned(db, game_id, user)
            simulation = read_simulation(state)
            await deliberation.apply(db, state, simulation, prepared, decision)
            return public_status(simulation)
    except SessionBusyError as exc:
        raise HTTPException(409, str(exc)) from None
    except ValidationError:
        raise HTTPException(
            502, "The model returned an invalid decision. No world change was applied."
        ) from None
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning(
            "Living World decision failed for session %s (%s)", game_id, type(exc).__name__
        )
        raise HTTPException(
            502, "Private decision failed. Check model settings and the inference queue."
        ) from None
    finally:
        deliberation.pending.pop(game_id, None)


@router.post("/{game_id}/living-world/cycle")
async def cycle(
    game_id: str,
    payload: Command,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    from backend.engine.living_world import cycles

    if user in db:
        db.expunge(user)
    await owned(db, game_id, user)
    if game_id in cycles.pending:
        raise HTTPException(409, "A Living World batch is already running.")
    stop = asyncio.Event()
    cycles.pending[game_id] = stop
    try:
        return await cycles.run(db, game_id, user, payload.expected_revision, deliberate, stop)
    except SessionBusyError as exc:
        raise HTTPException(409, str(exc)) from None
    finally:
        cycles.pending.pop(game_id, None)
