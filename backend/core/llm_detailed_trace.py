"""Opt-in wire-content observation before JSON parsing or narrative filtering."""

import re
from collections.abc import AsyncGenerator, AsyncIterator, Callable
from functools import wraps
from typing import Any

from backend.core.diagnostic_detail import value
from backend.core.diagnostic_fields import safe_error
from backend.core.system_diagnostics import service

REQUEST_FIELDS = (
    "model",
    "messages",
    "max_tokens",
    "max_completion_tokens",
    "temperature",
    "top_p",
    "top_k",
    "min_p",
    "repetition_penalty",
    "frequency_penalty",
    "presence_penalty",
    "stop",
    "response_format",
    "tools",
    "tool_choice",
    "stream",
    "seed",
    "extra_body",
    "format",
    "options",
    "thinking",
    "reasoning_effort",
)
MESSAGE_FIELDS = (
    "role",
    "content",
    "reasoning_content",
    "reasoning",
    "tool_calls",
    "function_call",
    "refusal",
)


class StreamBatch:
    def __init__(self, token: int) -> None:
        self.token = token
        self.chunks: list[dict] = []
        self.characters = 0

    def add(self, chunk: Any) -> None:
        if service.capture_token() != self.token:
            self.chunks.clear()
            return
        payload = response_payload(chunk)
        self.chunks.append(payload)
        self.characters += sum(len(str(choice["message"])) for choice in payload["choices"])
        if self.characters >= 4096:
            self.flush()

    def flush(self) -> None:
        if self.chunks:
            service.detail("detail.llm.stream", token=self.token, chunks=self.chunks)
        self.chunks, self.characters = [], 0


def field(item: Any, key: str, default: Any = None) -> Any:
    return item.get(key, default) if isinstance(item, dict) else getattr(item, key, default)


def response_payload(response: Any) -> dict:
    try:
        return _response_payload(response)
    except Exception as exc:
        return {"choices": [], "capture_error": type(exc).__name__}


def _response_payload(response: Any) -> dict:
    choices = []
    for choice in field(response, "choices", []) or []:
        message = field(choice, "delta") or field(choice, "message")
        choices.append(
            {
                "index": field(choice, "index", 0),
                "finish_reason": field(choice, "finish_reason"),
                "message": {
                    key: value(field(message, key))
                    for key in MESSAGE_FIELDS
                    if field(message, key) is not None
                },
            }
        )
    return {
        "choices": choices,
        "usage": value(field(response, "usage")),
        "model": field(response, "model"),
        "id": field(response, "id"),
    }


def request_payload(router: Any, kwargs: dict, token: int) -> None:
    service.detail(
        "detail.llm.request",
        token=token,
        provider=getattr(router, "provider", None),
        request={key: kwargs[key] for key in REQUEST_FIELDS if key in kwargs},
    )


def failure_payload(error: BaseException, kwargs: dict | None = None) -> dict:
    payload: dict = {"error": safe_error(error)}
    try:
        response = getattr(error, "response", None)
        text = getattr(response, "text", None)
        if isinstance(text, str):
            key = (kwargs or {}).get("api_key")
            if isinstance(key, str) and key:
                text = text.replace(key, "[credential excluded]")
            text = re.sub(r"\bsk-[A-Za-z0-9_-]{8,}", "[credential excluded]", text)
            payload["provider_response"] = {
                "status_code": getattr(response, "status_code", None),
                "body": text,
            }
    except Exception:
        payload["response_unavailable"] = True
    return payload


async def stream_response(stream: Any, token: int) -> AsyncGenerator[Any, None]:
    batch = StreamBatch(token)
    complete = False
    error = None
    try:
        async for chunk in stream:
            batch.add(chunk)
            yield chunk
        complete = True
    except BaseException as exc:
        error = safe_error(exc)
        raise
    finally:
        batch.flush()
        service.detail("detail.llm.stream.end", token=token, complete=complete, error=error)


class TracedStream(AsyncIterator[Any]):
    """Own the source even when the caller closes before requesting its first chunk."""

    def __init__(self, source: Any, token: int) -> None:
        self.source, self.token = source, token
        self.observed = stream_response(source, token)
        self.closed = False
        self.started = False

    def __aiter__(self) -> "TracedStream":
        return self

    async def __anext__(self) -> Any:
        self.started = True
        try:
            return await anext(self.observed)
        except BaseException:
            await self.aclose()
            raise

    async def aclose(self) -> None:
        if self.closed:
            return
        self.closed = True
        try:
            await self.observed.aclose()
            if not self.started:
                service.detail(
                    "detail.llm.stream.end", token=self.token, complete=False, reason="not_consumed"
                )
        finally:
            close = getattr(self.source, "aclose", None)
            if close is not None:
                await close()


def trace_async(method: Callable) -> Callable:
    @wraps(method)
    async def observed(router: Any, kwargs: dict) -> Any:
        token = service.capture_token()
        if token is None:
            return await method(router, kwargs)
        request_payload(router, kwargs, token)
        try:
            result = await method(router, kwargs)
        except BaseException as exc:
            service.detail("detail.llm.failed", token=token, **failure_payload(exc, kwargs))
            raise
        if kwargs.get("stream"):
            return TracedStream(result, token)
        service.detail("detail.llm.response", token=token, response=response_payload(result))
        return result

    return observed


def trace_sync(method: Callable) -> Callable:
    @wraps(method)
    def observed(router: Any, kwargs: dict) -> Any:
        token = service.capture_token()
        if token is None:
            return method(router, kwargs)
        request_payload(router, kwargs, token)
        try:
            result = method(router, kwargs)
        except BaseException as exc:
            service.detail("detail.llm.failed", token=token, **failure_payload(exc, kwargs))
            raise
        service.detail("detail.llm.response", token=token, response=response_payload(result))
        return result

    return observed
