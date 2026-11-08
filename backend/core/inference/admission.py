"""Bound queue waits by the selected model deadline; cancellation before admission is safe."""

import asyncio
import time
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import asynccontextmanager, contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from backend.core.config import settings
from backend.core.inference import events
from backend.core.inference.registry import (
    InferenceQueueError,
    InferenceUncertainError,
    Registry,
    Ticket,
)

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
    """Release on explicit rejection or failure before a connection can send the request."""
    return isinstance(error, (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout)) or (
        getattr(error, "status_code", None) in {400, 401, 403, 404, 405, 413, 415, 422, 429}
    )


@dataclass
class Lease:
    deadline: float
    certain: bool = False
    deferred: bool = False
    reason: str = "completion_unconfirmed"
    finalize: Callable[[bool, str], None] | None = None
    reservation_id: str | None = None


def failure_reason(error: BaseException) -> str:
    if isinstance(error, asyncio.CancelledError):
        return "caller_cancelled"
    if isinstance(error, TimeoutError) or "timeout" in type(error).__name__.lower():
        return "request_timeout"
    if isinstance(error, InferenceUncertainError):
        return "incomplete_stream"
    if (
        isinstance(error, (ConnectionError, OSError, httpx.ConnectError))
        or "connection" in type(error).__name__.lower()
    ):
        return "connection_failure"
    return "provider_or_processing_error"


@asynccontextmanager
async def reserve(key: str, timeout: float) -> AsyncIterator[Lease]:
    owner = registry()
    ticket = owner.enqueue(key)
    deadline = time.monotonic() + timeout
    acquired = False
    lease = Lease(
        deadline,
        finalize=lambda certain, reason: owner.finish(ticket, certain=certain, reason=reason),
        reservation_id=ticket.token,
    )
    started = time.monotonic()
    events.emit("queued", reservation_id=ticket.token, timeout_seconds=timeout)
    try:
        while not acquired:
            if time.monotonic() >= deadline:
                raise InferenceQueueError("Timed out waiting for the AI server queue.")
            acquired = owner.try_acquire(ticket, background_ready=ready(ticket))
            if not acquired:
                await asyncio.sleep(0.025)
        events.emit(
            "admitted", reservation_id=ticket.token, duration_ms=(time.monotonic() - started) * 1000
        )
        try:
            yield lease
        except BaseException as error:
            lease.certain = lease.certain or rejected(error)
            lease.reason = failure_reason(error)
            raise
    except BaseException as error:
        if not acquired:
            events.emit(
                "blocked",
                reservation_id=ticket.token,
                error=error,
                duration_ms=(time.monotonic() - started) * 1000,
            )
        raise
    finally:
        owner.forget(ticket)
        if acquired and not lease.deferred:
            owner.finish(ticket, certain=lease.certain, reason=lease.reason)
            events.emit(
                "completed" if lease.certain else "uncertain",
                reservation_id=ticket.token,
                duration_ms=(time.monotonic() - started) * 1000,
                inference_reason=None if lease.certain else lease.reason,
            )


@contextmanager
def reserve_sync(key: str, timeout: float) -> Iterator[Lease]:
    owner = registry()
    ticket = owner.enqueue(key)
    deadline = time.monotonic() + timeout
    acquired = False
    lease = Lease(deadline)
    started = time.monotonic()
    events.emit("queued", reservation_id=ticket.token, timeout_seconds=timeout)
    try:
        while not acquired:
            if time.monotonic() >= deadline:
                raise InferenceQueueError("Timed out waiting for the AI server queue.")
            acquired = owner.try_acquire(ticket, background_ready=ready(ticket))
            if not acquired:
                _check_sync_wait()
                time.sleep(0.025)
        events.emit(
            "admitted", reservation_id=ticket.token, duration_ms=(time.monotonic() - started) * 1000
        )
        try:
            yield lease
        except BaseException as error:
            lease.certain = lease.certain or rejected(error)
            lease.reason = failure_reason(error)
            raise
    except BaseException as error:
        if not acquired:
            events.emit(
                "blocked",
                reservation_id=ticket.token,
                error=error,
                duration_ms=(time.monotonic() - started) * 1000,
            )
        raise
    finally:
        owner.forget(ticket)
        if acquired:
            owner.finish(ticket, certain=lease.certain, reason=lease.reason)


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
