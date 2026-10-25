"""Give streamed turns priority over bounded, cooperative maintenance work.

Priority is process-local, matching the application's single-worker launcher.
An already submitted HTTP request may still occupy the remote model; beginning a
turn never waits for a background queue or attempts to cancel remote inference.
"""

import asyncio
import time
from collections.abc import AsyncIterator, Callable
from contextlib import aclosing, asynccontextmanager
from functools import wraps
from typing import Any

IDLE_GRACE_SECONDS = 15.0


class BackgroundDeferredError(Exception):
    """A player became active before a maintenance model request was submitted."""


class IdleScheduler:
    """Serialize maintenance and require a fresh quiet period after each job."""

    def __init__(self, grace_seconds: float = IDLE_GRACE_SECONDS) -> None:
        self.grace_seconds = grace_seconds
        self.active_turns = 0
        self.last_activity = time.monotonic()
        self.changed = asyncio.Event()
        self.capacity = asyncio.Lock()

    def _touch(self) -> None:
        self.last_activity = time.monotonic()
        self.changed.set()

    def can_start_background(self) -> bool:
        return not self.active_turns and time.monotonic() - self.last_activity >= self.grace_seconds

    @asynccontextmanager
    async def foreground(self) -> AsyncIterator[None]:
        self.active_turns += 1
        self._touch()
        try:
            yield
        finally:
            self.active_turns -= 1
            self._touch()

    async def wait_idle(self) -> None:
        while True:
            self.changed.clear()
            remaining = self.grace_seconds - (time.monotonic() - self.last_activity)
            if not self.active_turns and remaining <= 0:
                return
            timeout = None if self.active_turns else max(remaining, 0)
            try:
                await asyncio.wait_for(self.changed.wait(), timeout=timeout)
            except TimeoutError:
                continue

    @asynccontextmanager
    async def background(self) -> AsyncIterator[None]:
        async with self.capacity:
            await self.wait_idle()
            try:
                yield
            finally:
                self._touch()


scheduler = IdleScheduler()


async def _queue_initialized_turn(manager: Any) -> None:
    from backend.engine.memory_rag.worker import request_update

    session_id = getattr(getattr(manager, "state", None), "session_id", None)
    user_id = getattr(getattr(manager, "user", None), "id", None)
    if session_id and user_id:
        await request_update(session_id, user_id)


@asynccontextmanager
async def _turn_scope(manager: Any) -> AsyncIterator[None]:
    async with scheduler.foreground():
        try:
            yield
        finally:
            await _queue_initialized_turn(manager)


def foreground_turn(
    method: Callable[..., AsyncIterator[str]],
) -> Callable[..., AsyncIterator[str]]:
    """Register before turn initialization and release on errors/disconnects."""

    @wraps(method)
    async def guarded(manager: Any, *args: Any, **kwargs: Any) -> AsyncIterator[str]:
        async with _turn_scope(manager), aclosing(method(manager, *args, **kwargs)) as stream:
            async for chunk in stream:
                yield chunk

    return guarded
