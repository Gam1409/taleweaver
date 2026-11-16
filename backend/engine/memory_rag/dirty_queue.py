"""Coalesce optional memory refreshes outside the streamed request's transaction."""

import asyncio
import logging
from dataclasses import dataclass

from backend.engine.memory_rag import scheduling
from backend.engine.memory_rag.sqlite_busy import is_sqlite_busy

logger = logging.getLogger(__name__)
RETRY_INITIAL_SECONDS = 0.5
RETRY_MAX_SECONDS = 30.0
Key = tuple[str, str]


@dataclass
class PendingRefresh:
    requested: int = 1
    completed: int = 0
    attempted: int = 0
    task: asyncio.Task | None = None


_pending: dict[Key, PendingRefresh] = {}
_stopping = asyncio.Event()


def queue_refresh(session_id: str, user_id: str) -> None:
    """Record an intent without waiting on SQL, the caller's session or an LLM.

    New intents during an attempt remain pending for a subsequent fresh transaction.
    The task is retained until completion and cancelled/awaited during shutdown.
    """
    if _stopping.is_set():
        return
    key = (session_id, user_id)
    pending = _pending.get(key)
    if pending is not None:
        pending.requested += 1
        return
    pending = PendingRefresh()
    _pending[key] = pending
    _start(key, pending)


def _start(key: Key, pending: PendingRefresh) -> None:
    task = asyncio.create_task(_run(key, pending))
    pending.task = task
    task.add_done_callback(lambda finished: _finish(key, pending, finished))


async def _attempt(key: Key, pending: PendingRefresh) -> None:
    from backend.engine.memory_rag.worker import request_update

    # Record the attempted intent even if acquiring the scheduler gate fails.
    pending.attempted = pending.requested
    # This gate releases the request first and serializes optional maintenance.
    # request_update owns and closes its entire DB transaction before returning.
    async with scheduling.scheduler.background():
        pending.attempted = pending.requested
        await request_update(*key)
    pending.completed = pending.attempted


async def _wait_retry(failures: int) -> None:
    delay = min(RETRY_INITIAL_SECONDS * (2 ** min(failures - 1, 10)), RETRY_MAX_SECONDS)
    await asyncio.sleep(delay)


async def _run(key: Key, pending: PendingRefresh) -> None:
    failures = 0
    while pending.completed < pending.requested:
        try:
            await _attempt(key, pending)
            failures = 0
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if not is_sqlite_busy(exc):
                pending.completed = pending.attempted
                logger.exception("Could not refresh memory queue for session %s", key[0])
                return
            failures += 1
            logger.debug("Memory queue is busy for session %s; deferring retry", key[0])
            # No SQL session is open during backoff, including WAL snapshot retries.
            await _wait_retry(failures)


def _finish(key: Key, pending: PendingRefresh, task: asyncio.Task) -> None:
    if _pending.get(key) is not pending or pending.task is not task:
        return
    if task.cancelled():
        _pending.pop(key, None)
        return
    error = task.exception()
    if error is not None:
        logger.error("Memory refresh task failed for session %s", key[0], exc_info=error)
        _pending.pop(key, None)
        return
    if not _stopping.is_set() and pending.requested > pending.completed:
        _start(key, pending)
        return
    _pending.pop(key, None)


async def shutdown() -> None:
    """Drain owned tasks; no new intents or retry tasks are accepted while stopping."""
    _stopping.set()
    tasks = [pending.task for pending in _pending.values() if pending.task is not None]
    try:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    finally:
        _pending.clear()
        _stopping.clear()
