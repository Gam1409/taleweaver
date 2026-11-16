"""Task-local, content-free progress for explicitly enabled visual jobs."""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Literal

Stage = Literal["analyzing", "prompt", "submitting", "waiting", "downloading", "saving"]
_reporter: ContextVar[Callable[[Stage], None] | None] = ContextVar("visual_progress", default=None)


@contextmanager
def reporting(callback: Callable[[Stage], None] | None) -> Iterator[None]:
    token = _reporter.set(callback)
    try:
        yield
    finally:
        _reporter.reset(token)


def report(stage: Stage) -> None:
    callback = _reporter.get()
    if callback is not None:
        callback(stage)
