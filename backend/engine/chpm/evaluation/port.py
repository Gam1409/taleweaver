"""Measure logical router calls; keep missing provider usage unknown."""

import asyncio
import time
from collections.abc import Callable
from typing import Any

from backend.core.llm_usage_capture import capture_usage
from backend.engine.chpm.evaluation.contracts import Call


class MeasuredFactory:
    def __init__(self, factory: Callable[[str], Any], *, limit: int, timeout: float = 120):
        self.factory = factory
        self.limit = limit
        self.timeout = timeout
        self.calls: list[Call] = []

    def __call__(self, role: str) -> "MeasuredModel":
        return MeasuredModel(self.factory(role), role, self)


class MeasuredModel:
    def __init__(self, inner: Any, role: str, owner: MeasuredFactory):
        self.inner = inner
        self.role = role
        self.owner = owner
        self.model = inner.model
        self.provider = inner.provider
        self.max_tokens = inner.max_tokens
        self.enable_thinking = False
        self.request_timeout = min(float(inner.request_timeout), owner.timeout)

    async def aexecute_simple_task(
        self, system: str, content: str, model: str, **kwargs: Any
    ) -> str:
        if len(self.owner.calls) >= self.owner.limit:
            raise ValueError("Evaluation logical request limit exhausted.")
        call = Call(
            phase=kwargs.get("phase", "unknown"),
            role=self.role,
            model=self.model,
            provider=self.provider,
            input_chars=len(system) + len(content),
        )
        self.owner.calls.append(call)
        self.inner.max_tokens = self.max_tokens
        self.inner.enable_thinking = self.enable_thinking
        started = time.perf_counter()
        with capture_usage() as usage:
            try:
                result = await asyncio.wait_for(
                    self.inner.aexecute_simple_task(system, content, model, **kwargs),
                    timeout=self.request_timeout,
                )
                if not isinstance(result, str):
                    raise TypeError("Evaluation model returned a non-text response.")
                call.output_chars = len(result)
                call.returned_text = result[:64000]
                call.text_truncated = len(result) > 64000
                call.status = "ok"
                return result
            finally:
                call.elapsed_ms = (time.perf_counter() - started) * 1000
                # Multiple reported responses may represent retries. Do not pretend
                # one reported completion covers all physical attempts or billing.
                if len(usage) == 1:
                    call.prompt_tokens = usage[0]["prompt_tokens"]
                    call.completion_tokens = usage[0]["completion_tokens"]
