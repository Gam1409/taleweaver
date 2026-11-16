"""Opt-in, task-local capture of provider counts without prompts or credentials."""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

_capture: ContextVar[list[dict[str, int | None]] | None] = ContextVar("llm_usage", default=None)


@contextmanager
def capture_usage() -> Iterator[list[dict[str, int | None]]]:
    records: list[dict[str, int | None]] = []
    token = _capture.set(records)
    try:
        yield records
    finally:
        _capture.reset(token)


def record_usage(usage: Any) -> None:
    records = _capture.get()
    if records is None:
        return
    supplied = usage if isinstance(usage, dict) else {}
    records.append(
        {key: _count(supplied.get(key)) for key in ("prompt_tokens", "completion_tokens")}
    )


def _count(value: Any) -> int | None:
    return value if type(value) is int and value >= 0 else None
