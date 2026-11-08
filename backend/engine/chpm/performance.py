"""Bounded request timings retained with the completed NPC analysis."""

import time
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

from pydantic import Field

from backend.core import llm_timing
from backend.engine.chpm.core.contracts import Contract

actor_id: ContextVar[str] = ContextVar("chpm_timing_actor", default="")


class RequestTiming(Contract):
    actor_id: str = Field(default="", max_length=100)
    phase: str = Field(max_length=40)
    duration_ms: float = Field(ge=0)
    queue_ms: float | None = Field(default=None, ge=0)
    ttft_ms: float | None = Field(default=None, ge=0)
    prefill_ms: float | None = Field(default=None, ge=0)
    server_generation_ms: float | None = Field(default=None, ge=0)
    model_load_ms: float | None = Field(default=None, ge=0)
    cached_prompt_tokens: float | None = Field(default=None, ge=0)
    provider_attempts: int | None = Field(default=None, ge=0)


@contextmanager
def measure(usage: Any, phase: str) -> Iterator[None]:
    started = time.perf_counter()
    with llm_timing.capture() as records:
        try:
            yield
        finally:
            values = records[0] if len(records) == 1 else {}
            fields = {
                key: value for key, value in values.items() if key in RequestTiming.model_fields
            }
            fields["duration_ms"] = (time.perf_counter() - started) * 1000
            usage.timings.append(RequestTiming(actor_id=actor_id.get(), phase=phase, **fields))
