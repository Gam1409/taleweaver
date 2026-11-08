"""Bound independent NPC inference while keeping database work and result publication ordered."""

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any, cast

from backend.engine.chpm import actor_preparation, parallel_budget
from backend.engine.chpm.host_state import Mind
from backend.engine.chpm.schema import Decision, Observation
from backend.engine.turn_replay.transactions import release_for_model


async def prepare(
    manager: Any,
    turn: Any,
    actors: list[Any],
    observed: Observation,
    sequential: Callable[..., Awaitable[None]],
) -> None:
    ordered = sorted(actors, key=lambda actor: actor.id)
    if turn.initial.settings.npc_concurrency == 1 or len(ordered) < 2:
        for actor in ordered:
            await sequential(manager, turn, actor, observed)
        return
    jobs = [await actor_preparation.prepare(manager, turn, actor, observed) for actor in ordered]
    await release_for_model(manager)
    semaphore = asyncio.Semaphore(turn.initial.settings.npc_concurrency)
    normal_calls = 1 + (
        turn.initial.settings.agent_steps if turn.initial.settings.mode == "live" else 0
    )
    with parallel_budget.reserve([job.actor_id for job in jobs], normal_calls):
        tasks = [asyncio.create_task(_run(manager, turn, job, semaphore)) for job in jobs]
        try:
            results = await asyncio.gather(*tasks, return_exceptions=True)
        except BaseException:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise
    error = next((result for result in results if isinstance(result, BaseException)), None)
    if error is not None:
        raise error
    for job, result in zip(jobs, results, strict=True):
        actor_preparation.apply(turn, job.actor_id, cast(tuple[Decision, Mind | None], result))


async def _run(
    manager: Any, turn: Any, job: actor_preparation.PreparedActor, semaphore: asyncio.Semaphore
) -> tuple[Decision, Mind | None]:
    try:
        async with semaphore:
            return await actor_preparation.run(manager, turn, job)
    finally:
        parallel_budget.finished(job.actor_id)
