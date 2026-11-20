"""Give streamed turns priority over bounded, cooperative maintenance work.

Priority is process-local, matching the application's single-worker launcher.
When experimental inference admission is enabled, transport calls also share an
endpoint reservation. Already submitted background inference is not preempted.
"""

import asyncio
import time
from collections.abc import AsyncGenerator, AsyncIterator, Callable
from contextlib import aclosing, asynccontextmanager
from functools import wraps
from typing import Any

from backend.core.inference.registry import background_call

IDLE_GRACE_SECONDS = 15.0


class BackgroundDeferredError(Exception):
    """A player became active before a maintenance model request was submitted."""


class IdleScheduler:
    """Serialize maintenance and require a fresh quiet period after each job."""

    def __init__(self, grace_seconds: float = IDLE_GRACE_SECONDS) -> None:
        self.grace_seconds = grace_seconds
        self.active_turns = 0
        self.last_activity = time.monotonic()
        self.last_player_activity = self.last_activity
        self.changed = asyncio.Event()
        self.capacity = asyncio.Lock()

    def player_returned(self) -> None:
        """A visible session just opened or regained focus. Polling is not player activity."""
        self.last_player_activity = time.monotonic()
        self.changed.set()

    def _touch(self, *, player_turn: bool = False) -> None:
        self.last_activity = time.monotonic()
        if player_turn:
            self.last_player_activity = self.last_activity
        self.changed.set()

    def _remaining(self, player_idle_seconds: float) -> float:
        ready_at = max(
            self.last_activity + self.grace_seconds, self.last_player_activity + player_idle_seconds
        )
        return ready_at - time.monotonic()

    def can_start_background(self, *, player_idle_seconds: float = 0) -> bool:
        return not self.active_turns and self._remaining(player_idle_seconds) <= 0

    @asynccontextmanager
    async def foreground(self) -> AsyncIterator[None]:
        priority = background_call.set(False)
        self.active_turns += 1
        self._touch(player_turn=True)
        try:
            yield
        finally:
            background_call.reset(priority)
            self.active_turns -= 1
            self._touch(player_turn=True)

    async def wait_idle(self, *, player_idle_seconds: float = 0) -> None:
        while True:
            self.changed.clear()
            remaining = self._remaining(player_idle_seconds)
            if not self.active_turns and remaining <= 0:
                return
            timeout = None if self.active_turns else max(remaining, 0)
            try:
                await asyncio.wait_for(self.changed.wait(), timeout=timeout)
            except TimeoutError:
                continue

    @asynccontextmanager
    async def background(self, *, player_idle_seconds: float = 0) -> AsyncIterator[None]:
        while True:
            # Leave maintenance capacity free during the longer player-only quiet window.
            if player_idle_seconds:
                await self.wait_idle(player_idle_seconds=player_idle_seconds)
            async with self.capacity:
                await self.wait_idle()
                if player_idle_seconds and self._remaining(player_idle_seconds) > 0:
                    continue
                priority = background_call.set(True)
                try:
                    yield
                finally:
                    background_call.reset(priority)
                    self._touch()
                return


scheduler = IdleScheduler()


async def _queue_initialized_turn(manager: Any) -> None:
    from backend.engine.memory_rag.dirty_queue import queue_refresh

    session_id = getattr(getattr(manager, "state", None), "session_id", None)
    user_id = getattr(getattr(manager, "user", None), "id", None)
    if session_id and user_id:
        queue_refresh(session_id, user_id)


@asynccontextmanager
async def _turn_scope(manager: Any) -> AsyncIterator[None]:
    async with scheduler.foreground():
        interrupted = False
        try:
            yield
        except (asyncio.CancelledError, GeneratorExit):
            interrupted = True
            raise
        finally:
            # A disconnected stream may still own uncommitted writes. Do not open
            # a second transaction from its cancelled cleanup path.
            if not interrupted:
                await _queue_initialized_turn(manager)


def foreground_turn(
    method: Callable[..., AsyncGenerator[str, None]],
) -> Callable[..., AsyncGenerator[str, None]]:
    """Register before turn initialization and release on errors/disconnects."""

    @wraps(method)
    async def guarded(manager: Any, *args: Any, **kwargs: Any) -> AsyncGenerator[str, None]:
        async with _turn_scope(manager), aclosing(method(manager, *args, **kwargs)) as stream:
            async for chunk in stream:
                yield chunk

    return guarded
