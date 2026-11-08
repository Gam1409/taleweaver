"""Content-free LLM lifecycle events, independent of optional raw LLM telemetry."""

import asyncio
import logging
import math
import time
from collections.abc import AsyncIterator, Callable, Coroutine
from contextlib import AbstractContextManager, asynccontextmanager
from functools import wraps
from inspect import signature
from typing import Any, ParamSpec, TypeVar, cast
from uuid import UUID, uuid4

from backend.core.diagnostic_fields import ENUMS

logger = logging.getLogger(__name__)

_F = TypeVar("_F", bound=Callable[..., Any])

_P = ParamSpec("_P")
_R = TypeVar("_R")

_EVENTS = {
    "adventure.generation.apply_manifest.complete",
    "adventure.generation.apply_manifest.start",
    "adventure.generation.manifest_received",
    "adventure.generation.start",
    "adventure.generation.status",
    "adventure.generation.world_applied",
    "gm.turn.memory_recall",
    "gm.turn.pipeline.context",
    "gm.turn.pipeline.cycle_total",
    "gm.turn.pipeline.pass",
    "gm.turn.pipeline.tokens",
    "gm.turn.pipeline.total",
    "gm.turn.request",
    "gm.turn.response",
    "gm.turn.stream.request",
    "llm_interaction",
}
_NUMBERS = {
    "duration_ms",
    "prompt_tokens",
    "completion_tokens",
    "total_tokens",
    "cached_prompt_tokens",
    "history_messages_count",
    "memory_turns",
    "chars",
}
_IDS = {"adventure_id", "game_id", "message_id", "turn_id"}
_PROVIDERS = {
    "openai",
    "custom_openai",
    "ollama",
    "anthropic",
    "gemini",
    "openrouter",
    "deepseek",
    "mistral",
    "groq",
    "minimax",
    "kimi",
    "together_ai",
    "fireworks_ai",
    "comfyui",
    "stable_diffusion",
    "bfl",
    "black_forest_labs",
}
_ROLES = {"small", "complex", "generator", "compression", "play_agent"}


def emit(event: str, **fields: Any) -> None:
    from backend.core.system_diagnostics import service

    service.emit(event, **fields)
    if event in {"llm.started", "llm.completed", "llm.failed", "llm.cancelled"}:
        from backend.core.diagnostic_fields import safe_error

        fields = {**service.current_context(), **fields}
        error = fields.get("error")
        logger.info(
            "%s request=%s call=%s role=%s purpose=%s phase=%s timeout=%s max_tokens=%s thinking=%s elapsed_ms=%s error=%s",
            event,
            fields.get("request_id", "-"),
            fields.get("call_id", "-"),
            fields.get("role", "-"),
            fields.get("purpose", "-"),
            fields.get("phase", "-"),
            fields.get("timeout_seconds", "-"),
            fields.get("max_tokens", "-"),
            fields.get("thinking", "-"),
            fields.get("duration_ms", "-"),
            safe_error(error) if isinstance(error, BaseException) else "-",
        )


def _scope(context: dict) -> AbstractContextManager[None]:
    from backend.core.system_diagnostics import service

    return service.context(**context)


def _identifiers(fields: dict) -> dict:
    result = {}
    for key in _IDS:
        value = fields.get(key)
        if not isinstance(value, str):
            continue
        try:
            result[key] = str(UUID(value))
        except ValueError:
            continue
    return result


def _purpose(fields: dict) -> dict:
    result = {}
    for key, value in (("purpose", fields.get("operation")), ("phase", fields.get("phase"))):
        if isinstance(value, str) and value in ENUMS.get(key, set()):
            result[key] = value
    return result


def retry(router: Any, attempt: int, delay: float = 0, error: BaseException | None = None) -> None:
    fields: dict[str, float | str | BaseException] = {
        "attempt": attempt,
        "delay_ms": delay * 1000,
    }
    provider = getattr(router, "provider", None)
    if isinstance(provider, str) and provider in _PROVIDERS:
        fields["provider"] = provider
    if error is not None:
        fields["error"] = error
    emit("llm.retry", **fields)


def bridge_event(event: str, fields: dict) -> None:
    """Never forward opaque metadata, model names, text or raw response dictionaries."""
    if not isinstance(event, str) or event not in _EVENTS:
        return
    safe = {**_identifiers(fields), **_purpose(fields)}
    for key in _NUMBERS:
        value = fields.get(key)
        if (
            (type(value) is int or type(value) is float)
            and abs(value) <= 10**15
            and math.isfinite(value)
        ):
            safe[key] = value
    provider = fields.get("provider")
    if isinstance(provider, str) and provider in _PROVIDERS:
        safe["provider"] = provider
    for key in ("retrieval_method", "audience"):
        value = fields.get(key)
        if isinstance(value, str) and value in ENUMS[key]:
            safe[key] = value
    emit(event, **safe)


def _context(router: Any, kind: str, kwargs: dict) -> dict:
    context = {
        **_identifiers(kwargs),
        **_purpose(kwargs),
        "operation": kind,
        "call_id": str(uuid4()),
        "timeout_seconds": getattr(router, "request_timeout", None),
        "max_tokens": getattr(router, "max_tokens", None),
        "thinking": getattr(router, "enable_thinking", None),
    }
    provider = getattr(router, "provider", None)
    if isinstance(provider, str) and provider in _PROVIDERS:
        context["provider"] = provider
    role = getattr(router, "model_category", None)
    if isinstance(role, str) and role in _ROLES:
        context["role"] = role
    return context


def _finish(
    context: dict, start: float, error: BaseException | None = None, *, namespace: str = "llm"
) -> None:
    fields = {**context, "duration_ms": round((time.perf_counter() - start) * 1000, 3)}
    event = f"{namespace}.completed"
    if error is not None:
        event = (
            f"{namespace}.cancelled"
            if isinstance(error, (asyncio.CancelledError, GeneratorExit))
            else f"{namespace}.failed"
        )
        fields["error"] = error
    emit(event, **fields)


async def _stream(stream: Any, context: dict, start: float) -> AsyncIterator:
    try:
        async with _owned_scope(stream, context):
            async for chunk in _scoped_chunks(stream, context):
                yield chunk
    except BaseException as error:
        _finish(context, start, error)
        raise
    else:
        _finish(context, start)


@asynccontextmanager
async def _owned_scope(stream: Any, context: dict) -> AsyncIterator[None]:
    try:
        yield
    finally:
        with _scope(context):
            await stream.aclose()


async def _scoped_chunks(stream: Any, context: dict) -> AsyncIterator:
    iterator = aiter(stream)
    while True:
        try:
            with _scope(context):
                chunk = await anext(iterator)
        except StopAsyncIteration:
            return
        yield chunk


def async_call(kind: str) -> Callable[[_F], _F]:
    """Observe the public operation without inspecting its prompt arguments or result."""

    def decorate(method: _F) -> _F:
        @wraps(method)
        async def observed(router: Any, *args: Any, **kwargs: Any) -> Any:
            context, start = _context(router, kind, kwargs), time.perf_counter()
            emit("llm.started", **context)
            try:
                with _scope(context):
                    result = await method(router, *args, **kwargs)
            except BaseException as error:
                _finish(context, start, error)
                raise
            if kind == "stream":
                return _stream(result, context, start)
            _finish(context, start)
            return result

        return cast(_F, observed)

    return decorate


def sync_call(kind: str) -> Callable[[_F], _F]:
    def decorate(method: _F) -> _F:
        @wraps(method)
        def observed(router: Any, *args: Any, **kwargs: Any) -> Any:
            context, start = _context(router, kind, kwargs), time.perf_counter()
            emit("llm.started", **context)
            try:
                with _scope(context):
                    result = method(router, *args, **kwargs)
            except BaseException as error:
                _finish(context, start, error)
                raise
            _finish(context, start)
            return result

        return cast(_F, observed)

    return decorate


def async_operation(
    kind: str,
) -> Callable[[Callable[_P, Coroutine[Any, Any, _R]]], Callable[_P, Coroutine[Any, Any, _R]]]:
    """Observe embedding/image calls without copying their arguments into diagnostics."""

    def decorate(
        method: Callable[_P, Coroutine[Any, Any, _R]],
    ) -> Callable[_P, Coroutine[Any, Any, _R]]:
        call_signature = signature(method)

        @wraps(method)
        async def observed(*args: _P.args, **kwargs: _P.kwargs) -> _R:
            arguments = call_signature.bind(*args, **kwargs)
            arguments.apply_defaults()
            values = arguments.arguments
            context = {**_identifiers(values), "operation": kind, "call_id": str(uuid4())}
            provider = values.get("provider") or getattr(values.get("settings"), "provider", None)
            if isinstance(provider, str) and provider in _PROVIDERS:
                context["provider"] = provider
            if kind == "embedding" and isinstance(values.get("texts"), (list, tuple)):
                context["count"] = len(values["texts"])
            start = time.perf_counter()
            emit(f"{kind}.started", **context)
            try:
                result = await method(*args, **kwargs)
            except BaseException as error:
                _finish(context, start, error, namespace=kind)
                raise
            if kind == "image" and not result:
                _finish(
                    context,
                    start,
                    RuntimeError("Image generation returned no image"),
                    namespace=kind,
                )
            else:
                _finish(context, start, namespace=kind)
            return result

        return observed

    return decorate
