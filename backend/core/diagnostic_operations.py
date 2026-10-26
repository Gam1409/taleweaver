"""Trace background job lifecycles without serializing their inputs or outputs."""

import asyncio
import time
from collections.abc import Awaitable, Callable
from functools import wraps
from typing import ParamSpec, TypeVar
from uuid import uuid4

P = ParamSpec("P")
T = TypeVar("T")
_OPERATIONS = {"memory_maintenance", "npc_learning", "npc_portrait", "scene_background"}


def _service():
    from backend.core.system_diagnostics import service

    return service


def diagnostic_job(operation: str):
    """Decorate a coroutine whose first argument is its session ID."""
    if operation not in _OPERATIONS:
        raise ValueError("Unknown diagnostic job operation")

    def decorate(function: Callable[P, Awaitable[T]]) -> Callable[P, Awaitable[T]]:
        @wraps(function)
        async def run(*args: P.args, **kwargs: P.kwargs) -> T:
            service = _service()
            if not service.enabled:
                return await function(*args, **kwargs)
            session_id = args[0] if args else kwargs.get("session_id")
            fields = {"operation": operation, "call_id": uuid4().hex}
            started = time.perf_counter()
            with service.context(session_id=session_id):
                service.emit("job.started", **fields)
                try:
                    result = await function(*args, **kwargs)
                except BaseException as error:
                    name = (
                        "job.cancelled"
                        if isinstance(error, asyncio.CancelledError)
                        else "job.failed"
                    )
                    service.emit(name, **fields, duration_ms=_elapsed(started), error=error)
                    raise
                service.emit("job.completed", **fields, duration_ms=_elapsed(started))
                return result

        return run

    return decorate


def _elapsed(started: float) -> float:
    return (time.perf_counter() - started) * 1000
