"""Nonblocking leases for turn/settings writers in a single application worker.

The standard launcher runs one worker. This is an in-process asyncio guard, not a
cross-worker database lock. Multiple workers require a shared lease/version check.
Every writer that needs this protection must participate; background jobs and
other administrative state edits are outside this narrow turn/pace guard.
"""

import json
from collections.abc import AsyncGenerator, Callable, Iterator
from contextlib import aclosing, contextmanager
from dataclasses import dataclass
from functools import wraps
from typing import Any

BUSY_DETAIL = (
    "This session is busy. Wait for the current turn or settings update to finish, then try again."
)


@dataclass(frozen=True, eq=False)
class SessionLease:
    """Explicit capability for one active session writer; never inherited by child tasks."""

    session_id: str


_active_sessions: dict[str, SessionLease] = {}


class SessionBusyError(RuntimeError):
    """The caller must retry after the current writer completes."""


@contextmanager
def session_write_lease(
    session_id: str, *, lease: SessionLease | None = None
) -> Iterator[SessionLease]:
    """Check and acquire without an await: never queue while holding a DB transaction."""
    if lease is not None:
        if lease.session_id != session_id or _active_sessions.get(session_id) is not lease:
            raise SessionBusyError("The session writer lease is no longer active.")
        yield lease
        return
    if session_id in _active_sessions:
        raise SessionBusyError(BUSY_DETAIL)
    owned = SessionLease(session_id)
    _active_sessions[session_id] = owned
    try:
        yield owned
    finally:
        _active_sessions.pop(session_id, None)


def guard_session_turn(
    method: Callable[..., AsyncGenerator[str, None]],
) -> Callable[..., AsyncGenerator[str, None]]:
    """Acquire before manager initialization; close the inner stream on disconnect."""

    @wraps(method)
    async def guarded(manager: Any, *args: Any, **kwargs: Any) -> AsyncGenerator[str, None]:
        try:
            with session_write_lease(manager.game_id, lease=kwargs.get("session_lease")):
                async with aclosing(method(manager, *args, **kwargs)) as stream:
                    async for chunk in stream:
                        yield chunk
        except SessionBusyError as exc:
            yield (
                "event: error\ndata: "
                + json.dumps({"detail": str(exc), "retryable": True})
                + "\n\n"
            )

    return guarded
