"""Content-free latency measurements; unavailable server timings stay unknown."""

import math
import time
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any

_active: ContextVar["Measurement | None"] = ContextVar("llm_measurement", default=None)
_listeners: ContextVar[tuple[list[dict], ...]] = ContextVar("llm_timing_listeners", default=())


@dataclass
class Measurement:
    queue_ms: float = 0
    attempts: int = 0
    sent_at: float | None = None
    first_at: float | None = None
    provider: dict[str, float] = field(default_factory=dict)

    def fields(self) -> dict[str, float | int]:
        result: dict[str, float | int] = {
            "queue_ms": round(self.queue_ms, 3),
            "provider_attempts": self.attempts,
            **self.provider,
        }
        if self.first_at is not None and self.sent_at is not None:
            result["ttft_ms"] = round(max(0, self.first_at - self.sent_at) * 1000, 3)
            result["stream_generation_ms"] = round(
                max(0, time.perf_counter() - self.first_at) * 1000, 3
            )
        return result


@contextmanager
def activate(measurement: Measurement | None) -> Iterator[None]:
    token = _active.set(measurement)
    try:
        yield
    finally:
        _active.reset(token)


@contextmanager
def capture() -> Iterator[list[dict]]:
    records: list[dict] = []
    token = _listeners.set((*_listeners.get(), records))
    try:
        yield records
    finally:
        _listeners.reset(token)


def publish(fields: dict) -> None:
    keys = {
        "duration_ms",
        "queue_ms",
        "provider_attempts",
        "ttft_ms",
        "stream_generation_ms",
        "prefill_ms",
        "server_generation_ms",
        "model_load_ms",
        "cached_prompt_tokens",
    }
    record = {
        key: value for key, value in fields.items() if key in keys and _number(value) is not None
    }
    for listener in _listeners.get():
        listener.append(record)


def dispatched() -> None:
    measurement = _active.get()
    if measurement is not None:
        measurement.attempts += 1
        if measurement.sent_at is None:
            measurement.sent_at = time.perf_counter()


def queued(duration_ms: float) -> None:
    measurement = _active.get()
    if measurement is not None and _number(duration_ms) is not None:
        measurement.queue_ms += duration_ms


def first_chunk(chunk: Any) -> None:
    measurement = _active.get()
    if measurement is None or measurement.first_at is not None:
        return
    choices = getattr(chunk, "choices", None) or []
    if any(getattr(getattr(choice, "delta", None), "content", None) for choice in choices):
        measurement.first_at = time.perf_counter()


def record_response(response: Any) -> None:
    measurement = _active.get()
    if measurement is None or not isinstance(response, dict):
        return
    for source, target in (
        ("prompt_eval_duration", "prefill_ms"),
        ("eval_duration", "server_generation_ms"),
        ("load_duration", "model_load_ms"),
    ):
        value = _number(response.get(source))
        if value is not None:
            measurement.provider[target] = value / 1_000_000
    usage = response.get("usage")
    if not isinstance(usage, dict):
        return
    details = usage.get("prompt_tokens_details")
    cached = (
        details.get("cached_tokens")
        if isinstance(details, dict)
        else usage.get("cached_prompt_tokens")
    )
    value = _number(cached)
    if type(cached) is int and value is not None:
        measurement.provider["cached_prompt_tokens"] = value


def _number(value: object) -> float | None:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not 0 <= value <= 10**15:
        return None
    number = float(value)
    return number if math.isfinite(number) else None
