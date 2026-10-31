"""Explicit bounded orchestration; no perpetual worker or automatic retries."""

import asyncio
from collections.abc import Awaitable, Callable

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from backend.engine.living_world import runner
from backend.engine.living_world.schema import Command
from backend.engine.living_world.state import load, public_status, reconcile, save
from backend.engine.visual_novel.concurrency import session_write_lease
from backend.models.user import User

pending: dict[str, asyncio.Event] = {}


async def run(
    db: AsyncSession,
    game_id: str,
    user: User,
    expected: int,
    decide: Callable[..., Awaitable[dict]],
    stop: asyncio.Event,
) -> dict:
    # Import lazily to keep the route's authorization policy in one place.
    from backend.api.routes.adventures.living_world import check_revision, game_row, owned

    result: dict = {}
    budget: runner.Budget | None = None
    for index in range(5):
        await db.rollback()
        with session_write_lease(game_id):
            state = await owned(db, game_id, user)
            simulation = load(state)
            check_revision(simulation, expected)
            if not simulation.settings.living_world_enabled:
                raise HTTPException(409, "Enable Living World first.")
            if stop.is_set():
                return public_status(simulation)
            game = await game_row(db, game_id)
            reconcile(simulation, int(state.in_game_time or 0), game.living_world_presence)
            save(state, simulation)
            await db.commit()
            if budget is None:
                budget = runner.Budget.for_simulation(simulation)
            await runner.run(db, state, simulation, budget=budget)
            result = public_status(simulation)
        if (
            result["status"] != "WAITING_FOR_LLM"
            or not simulation.settings.deliberation_enabled
            or index >= simulation.settings.max_decisions_per_run
            or stop.is_set()
        ):
            return result
        result = await decide(game_id, Command(expected_revision=result["revision"]), db, user)
        budget.events_left -= 1
        budget.processed += 1
        expected = result["revision"]
    return result
