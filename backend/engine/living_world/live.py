"""Presence-triggered bounded background cycles for a single backend worker.

Game time still belongs to narration. Heartbeats provide opportunities to process
scheduled events, not permission to advance an emotional scene by wall-clock time.
"""

import asyncio
import logging
import time
from collections import OrderedDict
from dataclasses import dataclass

from fastapi import HTTPException

from backend.core.database import AsyncSessionLocal
from backend.engine.living_world import cycles, deliberation, runner
from backend.engine.living_world.conflicts import SimulationConflict
from backend.engine.living_world.presence import PRESENCE_GRACE_SECONDS
from backend.engine.living_world.schema import Command, Simulation
from backend.engine.living_world.state import load, reconcile
from backend.engine.memory_rag.scheduling import scheduler
from backend.models.game_session import GameSession
from backend.models.user import User

logger = logging.getLogger(__name__)


@dataclass
class Runtime:
    signature: str
    next_check: float = 0
    error: str = ""
    paused: bool = False
    task: asyncio.Task | None = None
    interval: int = 60


runtimes: OrderedDict[str, Runtime] = OrderedDict()


def signature(simulation: Simulation) -> str:
    return simulation.timeline + simulation.settings.model_dump_json()


def active(raw: dict | None) -> bool:
    now = time.time()
    return any(
        row.get("active") and now - row.get("seen", 0) <= PRESENCE_GRACE_SECONDS
        for row in (raw or {}).get("clients", {}).values()
    )


def due(simulation: Simulation) -> bool:
    return (
        simulation.target > simulation.cursor
        or runner.next_event(simulation, simulation.target) is not None
        or (
            simulation.settings.auto_schedule
            and simulation.settings.deliberation_enabled
            and simulation.schedule_next_due <= simulation.target
        )
    )


def status(game_id: str) -> dict:
    runtime = runtimes.get(game_id)
    return {
        "live_running": bool(runtime and runtime.task and not runtime.task.done()),
        "live_paused": bool(runtime and runtime.paused),
        "live_error": runtime.error if runtime else "",
    }


def reset(game_id: str) -> None:
    runtime = runtimes.get(game_id)
    if runtime:
        runtime.paused = False
        runtime.error = ""
        runtime.next_check = 0


def pause(game_id: str, simulation: Simulation) -> None:
    runtime = runtimes.setdefault(game_id, Runtime(signature(simulation)))
    runtime.signature = signature(simulation)
    runtime.interval = simulation.settings.live_interval_seconds
    runtime.paused = True


def notify(game_id: str, user_id: str, simulation: Simulation) -> None:
    if not simulation.settings.living_world_enabled or not simulation.settings.live_enabled:
        return
    runtime = runtimes.get(game_id)
    if runtime and runtime.task and not runtime.task.done():
        return
    key = signature(simulation)
    if runtime is None or runtime.signature != key:
        # Bound runtime bookkeeping without evicting a running task.
        if len(runtimes) >= 256:
            removable = next((key for key, row in runtimes.items() if not row.task), None)
            if removable is None:
                return
            runtimes.pop(removable)
        runtime = Runtime(key, interval=simulation.settings.live_interval_seconds)
        runtimes[game_id] = runtime
    if runtime.paused or time.monotonic() < runtime.next_check:
        return
    if not simulation.settings.allow_concurrent_requests and not scheduler.can_start_background():
        return
    if game_id in cycles.pending or game_id in deliberation.pending or game_id in runner.running:
        return
    runtime.next_check = time.monotonic() + simulation.settings.live_interval_seconds
    runtime.task = asyncio.create_task(_tick(game_id, user_id, runtime))


async def _tick(game_id: str, user_id: str, runtime: Runtime) -> None:
    from backend.api.routes.adventures.living_world import owned
    from backend.api.routes.adventures.living_world_decisions import cycle

    try:
        async with AsyncSessionLocal() as db:
            user = await db.get(User, user_id)
            game = await db.get(GameSession, game_id)
            if user is None or game is None or game.user_id != user_id:
                return
            state = await owned(db, game_id, user)
            simulation = load(state)
            if (
                runtime.paused
                or runtime.signature != signature(simulation)
                or not active(game.living_world_presence)
            ):
                return
            reconcile(simulation, int(state.in_game_time or 0), game.living_world_presence)
            if not due(simulation):
                return
            logger.info("Living World automatic batch started: session=%s", game_id)
            await cycle(game_id, Command(expected_revision=simulation.revision), db, user)
            logger.info("Living World automatic batch completed: session=%s", game_id)
    except SimulationConflict:
        logger.info("Living World automatic batch deferred after state change: session=%s", game_id)
    except HTTPException as exc:
        # Conflicting turns are expected; all other failures need explicit recovery.
        from backend.engine.visual_novel.concurrency import BUSY_DETAIL

        if exc.detail != BUSY_DETAIL:
            runtime.paused = True
            runtime.error = str(exc.detail)
            logger.warning(
                "Living World automatic batch paused: session=%s status=%s",
                game_id,
                exc.status_code,
            )
    except Exception as exc:
        runtime.paused = True
        runtime.error = "Automatic processing failed. Review server diagnostics and retry."
        logger.warning(
            "Living World automatic batch failed: session=%s error=%s", game_id, type(exc).__name__
        )
    finally:
        runtime.next_check = max(runtime.next_check, time.monotonic() + runtime.interval)
        runtime.task = None


async def shutdown() -> None:
    tasks = [row.task for row in runtimes.values() if row.task]
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    runtimes.clear()
