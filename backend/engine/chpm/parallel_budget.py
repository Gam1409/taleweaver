"""Account for outstanding normal requests while sharing the existing single repair."""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

from backend.engine.chpm.performance import actor_id


@dataclass
class Pending:
    remaining: dict[str, int]


_pending: ContextVar[Pending | None] = ContextVar("chpm_pending_calls", default=None)


@contextmanager
def reserve(actors: list[str], calls_per_actor: int) -> Iterator[None]:
    token = _pending.set(Pending(dict.fromkeys(actors, calls_per_actor)))
    try:
        yield
    finally:
        _pending.reset(token)


def dispatched(phase: str) -> None:
    pending = _pending.get()
    actor = actor_id.get()
    if pending is None or actor not in pending.remaining:
        return
    if phase == "proposal":
        pending.remaining[actor] = 0
    elif phase == "agent_lookup":
        pending.remaining[actor] = max(1, pending.remaining[actor] - 1)


def finished(actor: str) -> None:
    pending = _pending.get()
    if pending is not None:
        pending.remaining[actor] = 0


def remaining(fallback: int) -> int:
    pending = _pending.get()
    return sum(pending.remaining.values()) if pending is not None else fallback
