"""Fair, bounded maintenance phases; independent providers get independent backoff."""

import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Literal

from backend.core.inference.registry import InferenceQueueError, InferenceUncertainError
from backend.engine.memory_rag.cancellation import find_cancellation
from backend.engine.memory_rag.scheduling import BackgroundDeferredError
from backend.engine.memory_rag.sqlite_busy import is_sqlite_busy

KINDS = ("index", "chronicle", "summary", "observer")
Job = Callable[[], Awaitable[bool]]


@dataclass
class Outcome:
    status: Literal["worked", "failed", "waiting", "ready"]
    index_idle: bool = False
    error: str | None = None


@dataclass
class Cycle:
    cursor: int = 0
    failures: dict[str, tuple[int, float]] = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)

    async def run(self, jobs: dict[str, Job]) -> Outcome:
        order = KINDS[self.cursor :] + KINDS[: self.cursor]
        index_idle = False
        for kind in order:
            if self.failures.get(kind, (0, 0))[1] > time.monotonic():
                continue
            self.cursor = (KINDS.index(kind) + 1) % len(KINDS)
            try:
                worked = await jobs[kind]()
            except Exception as exc:
                _propagate_control_error(exc)
                self._failed(kind, exc)
                return Outcome("failed", index_idle, self.errors[kind])
            self.failures.pop(kind, None)
            self.errors.pop(kind, None)
            index_idle = index_idle or (kind == "index" and not worked)
            if worked:
                return Outcome("worked", index_idle, self.notice())
        return Outcome("waiting" if self.failures else "ready", index_idle, self.notice())

    def _failed(self, kind: str, exc: Exception) -> None:
        attempt = self.failures.get(kind, (0, 0))[0] + 1
        delay = min(60 * 2 ** min(attempt - 1, 4), 900)
        self.failures[kind] = (attempt, time.monotonic() + delay)
        self.errors[kind] = (
            f"Memory {kind} deferred ({type(exc).__name__}). Check its model settings; other maintenance can continue."
        )

    def notice(self) -> str | None:
        return next(iter(self.errors.values()), None)


def _propagate_control_error(exc: Exception) -> None:
    if cancelled := find_cancellation(exc):
        raise cancelled
    if isinstance(
        exc, (InferenceQueueError, InferenceUncertainError, BackgroundDeferredError)
    ) or is_sqlite_busy(exc):
        raise exc


_cycles: OrderedDict[tuple[str, str, int], Cycle] = OrderedDict()


def cycle(session_id: str, user_id: str, epoch: int) -> Cycle:
    key = session_id, user_id, epoch
    if key not in _cycles:
        for previous in list(_cycles):
            if previous[:2] == key[:2]:
                del _cycles[previous]
        _cycles[key] = Cycle()
    _cycles.move_to_end(key)
    while len(_cycles) > 256:
        _cycles.popitem(last=False)
    return _cycles[key]


def clear() -> None:
    _cycles.clear()
