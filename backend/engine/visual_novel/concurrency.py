"""Nonblocking leases for turn/settings writers in a single application worker.

The standard launcher runs one worker. This is an in-process asyncio guard, not a
cross-worker database lock. Multiple workers require a shared lease/version check.
Every writer that needs this protection must participate; background jobs and
other administrative state edits are outside this narrow turn/pace guard.
"""

import json
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import aclosing, contextmanager
from functools import wraps
from typing import Any

BUSY_DETAIL = (
    "This session is busy. Wait for the current turn or settings update to finish, then try again."
)
_active_sessions: set[str] = set()


class SessionBusyError(RuntimeError):
    """The caller must retry after the current writer completes."""


@contextmanager
def session_write_lease(session_id: str) -> Iterator[None]:
    """Check and acquire without an await: never queue while holding a DB transaction."""
    if session_id in _active_sessions:
        raise SessionBusyError(BUSY_DETAIL)
    _active_sessions.add(session_id)
    try:
        yield
    finally:
        _active_sessions.discard(session_id)


def guard_session_turn(
    method: Callable[..., AsyncIterator[str]],
) -> Callable[..., AsyncIterator[str]]:
    """Acquire before manager initialization; close the inner stream on disconnect."""

    @wraps(method)
    async def guarded(manager: Any, *args: Any, **kwargs: Any) -> AsyncIterator[str]:
        try:
            with session_write_lease(manager.game_id):
                async with aclosing(method(manager, *args, **kwargs)) as stream:
                    async for chunk in stream:
                        yield chunk
        except SessionBusyError:
            yield (
                "event: error\ndata: "
                + json.dumps({"detail": BUSY_DETAIL, "retryable": True})
                + "\n\n"
            )

    return guarded
