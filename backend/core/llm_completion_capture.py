"""Task-local completion metadata, without retaining prompts or response text."""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

from backend.core.llm_finish_state import classify_tool_finish


@dataclass(frozen=True)
class Completion:
    finish_reason: str | None
    completion_tokens: int | None
    tool_finish_reason: str | None = None
    tool_rejected: bool = False


_listeners: ContextVar[tuple[list[Completion], ...]] = ContextVar("llm_completions", default=())


@contextmanager
def capture_completions() -> Iterator[list[Completion]]:
    """Nested observers both receive metadata; independent tasks remain isolated."""
    records: list[Completion] = []
    token = _listeners.set((*_listeners.get(), records))
    try:
        yield records
    finally:
        _listeners.reset(token)


def _tool_state(choice: Any) -> tuple[str | None, bool]:
    try:
        return classify_tool_finish(choice), False
    except ValueError:
        return None, True


def record_completion(response: Any) -> None:
    if not _listeners.get() or not isinstance(response, dict):
        return
    choices = response.get("choices")
    choice = choices[0] if isinstance(choices, list) and len(choices) == 1 else None
    reason = choice.get("finish_reason") if isinstance(choice, dict) else None
    # Unknown provider strings cannot leak unbounded/untrusted data into diagnostics.
    if reason not in ("stop", "length", "max_tokens", "content_filter", "tool_calls"):
        reason = None
    usage = response.get("usage")
    count = usage.get("completion_tokens") if isinstance(usage, dict) else None
    count = count if isinstance(choice, dict) and type(count) is int and count >= 0 else None
    tool_reason, tool_rejected = _tool_state(choice)
    record = Completion(
        finish_reason=reason,
        completion_tokens=count,
        tool_finish_reason=tool_reason,
        tool_rejected=tool_rejected,
    )
    for listener in _listeners.get():
        listener.append(record)
