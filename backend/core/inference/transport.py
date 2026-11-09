"""Transport boundaries: keep reservations until a response is known to have ended."""

from collections.abc import AsyncIterator, Callable, Coroutine
from contextlib import AsyncExitStack
from functools import wraps
from typing import Any

from backend.core import llm_timing
from backend.core.inference import admission, capacity, receipts
from backend.core.inference.registry import InferenceUncertainError


def target(router: Any, kwargs: dict | None = None) -> str | None:
    configured = getattr(router, "parallel_policy", None) is not None
    legacy = admission.enabled() and router.provider in {"ollama", "custom_openai"}
    if not configured and not legacy:
        return None
    return capacity.target(router, kwargs)


async def _stream(method: Callable, router: Any, kwargs: dict, key: str) -> AsyncIterator[Any]:
    async with admission.reserve(
        key, float(router.request_timeout), capacity=capacity.limit(router)
    ) as lease:
        with admission.deadline_scope(lease):
            llm_timing.dispatched()
            stream = await method(router, {**kwargs, "num_retries": 0})
        try:
            async for chunk in _chunks(stream, lease):
                choices = getattr(chunk, "choices", None) or []
                lease.certain = lease.certain or any(
                    getattr(choice, "finish_reason", None) for choice in choices
                )
                yield chunk
        finally:
            close = getattr(stream, "aclose", None)
            if close is not None:
                await close()
        if not lease.certain:
            raise InferenceUncertainError(
                "The AI stream ended without a completion marker. "
                "The administrator must check the inference queue before retrying."
            )


def guarded_async(method: Callable) -> Callable:
    @wraps(method)
    async def guarded(router: Any, kwargs: dict) -> Any:
        key = target(router, kwargs)
        if key is None:
            llm_timing.dispatched()
            return await method(router, kwargs)
        if kwargs.get("stream"):
            return _stream(method, router, kwargs, key)
        async with admission.reserve(
            key, float(router.request_timeout), capacity=capacity.limit(router)
        ) as lease:
            with admission.deadline_scope(lease):
                llm_timing.dispatched()
                result = await _outcome(method(router, {**kwargs, "num_retries": 0}), lease)
            lease.certain = True
            return result

    return guarded


def guarded_sync(method: Callable) -> Callable:
    @wraps(method)
    def guarded(router: Any, kwargs: dict) -> Any:
        key = target(router, kwargs)
        if key is None:
            llm_timing.dispatched()
            return method(router, kwargs)
        with admission.reserve_sync(
            key, float(router.request_timeout), capacity=capacity.limit(router)
        ) as lease:
            with admission.deadline_scope(lease):
                llm_timing.dispatched()
                result = method(router, {**kwargs, "num_retries": 0})
            lease.certain = True
            return result

    return guarded


async def owned_stream(output: Any, *sources: Any) -> AsyncIterator[Any]:
    """Close every filter layer immediately on early consumer exit, not on GC."""
    async with AsyncExitStack() as stack:
        for stream in (*reversed(sources), output):
            close = getattr(stream, "aclose", None)
            if close is not None:
                stack.push_async_callback(close)
        async for chunk in output:
            yield chunk


async def _outcome(request: Coroutine, lease: admission.Lease) -> Any:
    """A cancellation-resistant SDK must not return a late result to its caller."""
    return await receipts.wait_for_response(request, lease)


async def _chunks(stream: Any, lease: admission.Lease) -> AsyncIterator[Any]:
    iterator = aiter(stream)
    while True:
        try:
            with admission.deadline_scope(lease):
                chunk = await anext(iterator)
        except StopAsyncIteration:
            return
        yield chunk
