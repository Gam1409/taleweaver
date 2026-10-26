"""Retry short maintenance transactions without repeating model extraction."""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from functools import wraps
from typing import ParamSpec, TypeVar

from backend.engine.memory_rag import scheduling
from backend.engine.memory_rag.cancellation import find_cancellation
from backend.engine.memory_rag.sqlite_busy import is_sqlite_busy

logger = logging.getLogger(__name__)
RETRY_DELAYS = (0.2, 0.5, 1.0, 2.0)
P = ParamSpec("P")
T = TypeVar("T")


def retry_transaction(operation: Callable[P, Awaitable[T]]) -> Callable[P, Awaitable[T]]:
    """The operation must own and close its session on every attempt.

    A busy read-to-write upgrade requires a fresh transaction, not another SQL
    statement on the old snapshot. Callers must revalidate their claim and source.
    Cancellation and non-contention errors propagate immediately.
    """

    @wraps(operation)
    async def run(*args: P.args, **kwargs: P.kwargs) -> T:
        for attempt in range(len(RETRY_DELAYS) + 1):
            # Wait outside any SQL session: a turn can own the SQLite writer
            # while awaiting its model, much longer than a transient retry delay.
            task = asyncio.current_task()
            if scheduling.scheduler.active_turns and not (task and task.cancelling()):
                await scheduling.scheduler.wait_idle()
            try:
                return await operation(*args, **kwargs)
            except Exception as error:
                if cancelled := find_cancellation(error):
                    raise cancelled from None
                if not is_sqlite_busy(error) or attempt == len(RETRY_DELAYS):
                    raise
                logger.debug(
                    "Retrying maintenance transaction %s after SQLite contention",
                    operation.__name__,
                )
                await asyncio.sleep(RETRY_DELAYS[attempt])
        raise AssertionError("Unreachable retry state")

    return run
