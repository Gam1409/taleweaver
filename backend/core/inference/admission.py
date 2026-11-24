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

dispatch_guard: ContextVar[Callable[[], None] | None] = ContextVar(
    "inference_dispatch_guard", default=None
)


def check_dispatch_guard() -> None:
    guard = dispatch_guard.get()
    if guard is not None:
        guard()


_registry = Registry(Path(settings.DATA_DIR) / "inference-reservations.json")


def registry() -> Registry:
    return _registry


def enabled() -> bool:
    return settings.INFERENCE_SERIALIZATION_ENABLED


def ready(ticket: Ticket) -> bool:
    check_dispatch_guard()
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
    http_attempted: bool = False


_current_lease: ContextVar[Lease | None] = ContextVar("inference_lease", default=None)


def begin_http_request(request: httpx.Request) -> None:
    if (lease := _current_lease.get()) is not None and request.method == "POST":
        lease.http_attempted = True
        lease.certain = False


def confirm_local_rejection() -> None:
    if (lease := _current_lease.get()) is not None and not lease.http_attempted:
        lease.certain = True


async def receive_http_response(response: httpx.Response) -> None:
    """An entire successful non-streaming body survives later SDK parsing errors."""
    if (lease := _current_lease.get()) is not None and response.status_code == 200:
        await response.aread()
        lease.certain = True


def receive_http_response_sync(response: httpx.Response) -> None:
    if (lease := _current_lease.get()) is not None and response.status_code == 200:
        response.read()
        lease.certain = True


def failure_reason(error: BaseException) -> str:
    if isinstance(error, asyncio.CancelledError):
        return "caller_cancelled"
    if isinstance(error, TimeoutError) or "timeout" in type(error).__name__.lower():
        return "request_timeout"
    if isinstance(error, InferenceUncertainError):
        return "incomplete_stream"
    status = getattr(error, "status_code", None)
    if type(status) is int and 500 <= status < 600:
        return "provider_http_5xx"
    if (
        isinstance(error, (ConnectionError, OSError, httpx.ConnectError))
        or "connection" in type(error).__name__.lower()
    ):
        return "connection_failure"
    return "provider_or_processing_error"


def _queued(ticket: Ticket, timeout: float) -> None:
    events.emit(
        "queued",
        reservation_id=ticket.token,
        timeout_seconds=timeout,
        endpoint_fingerprint=ticket.key,
        max_concurrent=ticket.capacity + int(ticket.concurrent),
        concurrency_policy="configured" if ticket.configured else "legacy",
        background=ticket.background,
        concurrent_lane=ticket.concurrent,
    )


@asynccontextmanager
async def reserve(
    key: str, timeout: float, *, capacity: int | None = None, wait_for_slot: bool = True
) -> AsyncIterator[Lease]:
    owner = registry()
    ticket = owner.enqueue(key, capacity=capacity)
    deadline = time.monotonic() + timeout
    acquired = False
    lease = Lease(
        deadline,
        finalize=lambda certain, reason: owner.finish(ticket, certain=certain, reason=reason),
        reservation_id=ticket.token,
    )
    started = time.monotonic()
    _queued(ticket, timeout)
    try:
        while not acquired:
            if time.monotonic() >= deadline:
                raise InferenceQueueError("Timed out waiting for the AI server queue.")
            acquired = owner.try_acquire(ticket, background_ready=ready(ticket))
            if not acquired and not wait_for_slot:
                raise InferenceQueueError("No immediate inference slot is available.")
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
                blocking_reservation_id=getattr(error, "blocking_reservation_id", None),
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
def reserve_sync(key: str, timeout: float, *, capacity: int | None = None) -> Iterator[Lease]:
    owner = registry()
    ticket = owner.enqueue(key, capacity=capacity)
    deadline = time.monotonic() + timeout
    acquired = False
    lease = Lease(deadline)
    started = time.monotonic()
    _queued(ticket, timeout)
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
                blocking_reservation_id=getattr(error, "blocking_reservation_id", None),
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
    lease_token = _current_lease.set(lease)
    try:
        yield
    finally:
        _current_lease.reset(lease_token)
        request_deadline.reset(token)
