"""Keep ownership of a submitted request after its caller stops waiting."""

import asyncio
import logging
import time
from collections.abc import Coroutine
from typing import Any

from backend.core.inference import admission, events

logger = logging.getLogger(__name__)
_monitors: set[asyncio.Task] = set()


async def wait_for_response(request: Coroutine, lease: admission.Lease) -> Any:
    """Keep the submitted transport and its resources alive after a caller deadline."""
    task = asyncio.create_task(request)
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        follow(task, lease)
        raise


def completed(task: asyncio.Task, lease: admission.Lease) -> bool:
    """A transport response is proof; its obsolete text is never returned to the caller."""
    if task.cancelled():
        return False
    error = task.exception()
    if error is not None:
        lease.reason = admission.failure_reason(error)
        return admission.rejected(error)
    return True


def _finish(lease: admission.Lease, certain: bool) -> None:
    if lease.finalize is None:
        return
    try:
        lease.finalize(certain, lease.reason)
        events.emit(
            "completed" if certain else "uncertain",
            reservation_id=lease.reservation_id,
            inference_reason=None if certain else lease.reason,
        )
    except (OSError, ValueError):
        logger.exception("Could not record inference completion; the durable reservation remains.")


def _late(task: asyncio.Task, lease: admission.Lease) -> None:
    # Token matching in Registry.finish prevents an old receipt clearing a newer request.
    if completed(task, lease):
        _finish(lease, True)


async def _monitor(task: asyncio.Task, lease: admission.Lease) -> None:
    try:
        await asyncio.wait_for(asyncio.shield(task), max(0.001, lease.deadline - time.monotonic()))
    except (TimeoutError, asyncio.CancelledError):
        lease.reason = "request_timeout"
        task.cancel()
        _finish(lease, False)
        task.add_done_callback(lambda done: _late(done, lease))
    except Exception:
        _finish(lease, completed(task, lease))
    else:
        _finish(lease, completed(task, lease))


def follow(task: asyncio.Task[Any], lease: admission.Lease) -> None:
    """Bound RUNNING ownership by the existing deadline, then retain only a late receipt."""
    if task.done():
        lease.certain = completed(task, lease)
        return
    lease.deferred = True
    monitor = asyncio.create_task(_monitor(task, lease))
    _monitors.add(monitor)
    monitor.add_done_callback(_monitors.discard)
