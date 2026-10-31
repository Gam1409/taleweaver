"""Bound queue waits by the selected model deadline; cancellation before admission is safe."""

import asyncio
import time
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.core.config import settings
from backend.core.inference.registry import InferenceQueueError, Registry, Ticket

request_deadline: ContextVar[float | None] = ContextVar("inference_deadline", default=None)

_registry = Registry(Path(settings.DATA_DIR) / "inference-reservations.json")


def registry() -> Registry:
    return _registry


def enabled() -> bool:
    return settings.INFERENCE_SERIALIZATION_ENABLED


def ready(ticket: Ticket) -> bool:
    if not ticket.background or ticket.concurrent:
        return True
    from backend.engine.memory_rag.scheduling import scheduler

    return scheduler.can_start_background()


def rejected(error: BaseException) -> bool:
    """Explicit request rejection is safe; timeouts, disconnects and 5xx are uncertain."""
    return getattr(error, "status_code", None) in {400, 401, 403, 404, 405, 413, 415, 422, 429}


@dataclass
class Lease:
    deadline: float
    certain: bool = False


@asynccontextmanager
async def reserve(key: str, timeout: float) -> AsyncIterator[Lease]:
    owner = registry()
    ticket = owner.enqueue(key)
    deadline = time.monotonic() + timeout
    acquired = False
    lease = Lease(deadline)
    try:
        while not acquired:
            if time.monotonic() >= deadline:
                raise InferenceQueueError("Timed out waiting for the AI server queue.")
            acquired = owner.try_acquire(ticket, background_ready=ready(ticket))
            if not acquired:
                await asyncio.sleep(0.025)
        try:
            yield lease
        except BaseException as error:
            lease.certain = lease.certain or rejected(error)
            raise
    finally:
        owner.forget(ticket)
        if acquired:
            owner.finish(ticket, certain=lease.certain)


@contextmanager
def reserve_sync(key: str, timeout: float) -> Iterator[Lease]:
    owner = registry()
    ticket = owner.enqueue(key)
    deadline = time.monotonic() + timeout
    acquired = False
    lease = Lease(deadline)
    try:
        while not acquired:
            if time.monotonic() >= deadline:
                raise InferenceQueueError("Timed out waiting for the AI server queue.")
            acquired = owner.try_acquire(ticket, background_ready=ready(ticket))
            if not acquired:
                _check_sync_wait()
                time.sleep(0.025)
        try:
            yield lease
        except BaseException as error:
            lease.certain = lease.certain or rejected(error)
            raise
    finally:
        owner.forget(ticket)
        if acquired:
            owner.finish(ticket, certain=lease.certain)


def _check_sync_wait() -> None:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return
    raise InferenceQueueError("Use the async LLM API to wait for a busy server on the event loop.")


def timeout_for(router: Any) -> float:
    configured = float(router.request_timeout)
    deadline = request_deadline.get()
    return (
        configured if deadline is None else max(0.001, min(configured, deadline - time.monotonic()))
    )


@contextmanager
def deadline_scope(lease: Lease) -> Iterator[None]:
    """Use only around an await/call, never across an async generator yield."""
    token = request_deadline.set(lease.deadline)
    try:
        yield
    finally:
        request_deadline.reset(token)
