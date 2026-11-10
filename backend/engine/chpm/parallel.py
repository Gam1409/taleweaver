"""Bound independent NPC inference while keeping database work and result publication ordered."""

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any, cast

from backend.core.llm_parallel import npc_capacity
from backend.engine.chpm import actor_preparation, parallel_budget, proposal_failures
from backend.engine.chpm.errors import ProposalRejectedError
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
    settings = turn.initial.settings
    limit = npc_capacity(
        getattr(manager, "user", None), settings.model_role, settings.npc_concurrency
    )
    if limit == 1 or len(ordered) < 2:
        await _sequential(manager, turn, ordered, observed, sequential)
        return
    jobs = [await actor_preparation.prepare(manager, turn, actor, observed) for actor in ordered]
    await release_for_model(manager)
    semaphore = asyncio.Semaphore(limit)
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
    _publish(turn, jobs, results)


async def _sequential(
    manager: Any, turn: Any, actors: list[Any], observed: Observation, prepare: Callable
) -> None:
    failures = []
    for actor in actors:
        try:
            await prepare(manager, turn, actor, observed)
        except ProposalRejectedError as exc:
            if not proposal_failures.can_defer(turn, exc):
                raise
            proposal_failures.defer(turn, actor.id, exc)
            failures.append(exc)
    proposal_failures.require_survivor(turn, failures)


def _publish(turn: Any, jobs: list[actor_preparation.PreparedActor], results: list[Any]) -> None:
    error = next(
        (
            result
            for result in results
            if isinstance(result, BaseException) and not proposal_failures.can_defer(turn, result)
        ),
        None,
    )
    if error is not None:
        raise error
    failures = []
    for job, result in zip(jobs, results, strict=True):
        if isinstance(result, ProposalRejectedError):
            proposal_failures.defer(turn, job.actor_id, result)
            failures.append(result)
        else:
            actor_preparation.apply(turn, job.actor_id, cast(tuple[Decision, Mind | None], result))
    proposal_failures.require_survivor(turn, failures)


async def _run(
    manager: Any, turn: Any, job: actor_preparation.PreparedActor, semaphore: asyncio.Semaphore
) -> tuple[Decision, Mind | None]:
    try:
        async with semaphore:
            return await actor_preparation.run(manager, turn, job)
    finally:
        parallel_budget.finished(job.actor_id)
