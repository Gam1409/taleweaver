"""Opt-in structured calls have one physical attempt and require a complete response."""

import asyncio
import json
from unittest.mock import AsyncMock

import httpx
import pytest
from litellm import (
    APIConnectionError,
    BadRequestError,
    InternalServerError,
    RateLimitError,
    ServiceUnavailableError,
    Timeout,
)
from pydantic import BaseModel

from backend.core import custom_openai
from backend.core.llm_completion_capture import capture_completions
from backend.core.llm_output_errors import StructuredOutputError
from backend.core.llm_router import GameMasterLLM
from backend.models.user import User


class Answer(BaseModel):
    value: int


def router(monkeypatch, mode="prompt"):
    monkeypatch.setattr(custom_openai, "validate_custom_url", lambda value: value)
    result = GameMasterLLM(
        User(
            username="offline-structured",
            llm_settings={
                "custom_openai_url": "https://offline.invalid/v1",
                "custom_openai_response_format": mode,
            },
            encrypted_api_keys={},
        ),
        provider="custom_openai",
    )
    result.max_tokens, result.request_timeout, result.enable_thinking = 512, 2, False
    return result


def completion(content='{"value":7}', reason="stop", *, reasoning=None):
    return {
        "id": "offline-structured",
        "object": "chat.completion",
        "created": 1,
        "model": "local-model",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": content,
                    "reasoning_content": reasoning,
                },
                "finish_reason": reason,
            }
        ],
        "usage": {"prompt_tokens": 12, "completion_tokens": 8, "total_tokens": 20},
    }


def mock_http(monkeypatch, respond):
    seen = []

    async def send(_client, request, **_kwargs):
        seen.append(request)
        return await respond(request)

    def forbid_network(*_args, **_kwargs):
        raise AssertionError("The structured test must not open a network socket.")

    monkeypatch.setattr(httpx.AsyncClient, "send", send)
    monkeypatch.setattr("socket.socket.connect", forbid_network)
    return seen


@pytest.mark.parametrize("mode", ["prompt", "json_object", "json_schema"])
async def test_single_attempt_preserves_typed_result_and_selected_wire_contract(monkeypatch, mode):
    async def respond(request):
        return httpx.Response(200, json=completion(), request=request)

    llm = router(monkeypatch, mode)
    seen = mock_http(monkeypatch, respond)
    schema = Answer.model_json_schema()
    schema["properties"]["value"]["enum"] = [7]
    with capture_completions() as captured:
        result = await llm.aexecute_complex_task(
            "sys", "hi", Answer, "local-model", response_schema=schema, single_attempt=True
        )
    assert result == Answer(value=7) and len(seen) == len(captured) == 1
    body = json.loads(seen[0].content)
    assert body["max_tokens"] == 512
    assert "_single_attempt" not in body and "num_retries" not in body and "max_retries" not in body
    if mode == "json_schema":
        contract = body["response_format"]["json_schema"]["schema"]
        assert contract["properties"]["value"]["enum"] == [7]
    else:
        assert body.get("response_format") == (
            {"type": "json_object"} if mode == "json_object" else None
        )


async def test_single_attempt_empty_reasoning_response_never_sends_blank_retry(monkeypatch):
    async def respond(request):
        return httpx.Response(
            200, json=completion("", reasoning="Unfinished reasoning."), request=request
        )

    seen = mock_http(monkeypatch, respond)
    with capture_completions() as captured, pytest.raises(StructuredOutputError):
        await router(monkeypatch).aexecute_complex_task(
            "sys", "hi", Answer, "local-model", single_attempt=True
        )
    assert len(seen) == len(captured) == 1


@pytest.mark.parametrize(
    "reason", ["length", "max_tokens", "content_filter", "PRIVATE_UNKNOWN_FINISH", "tool_calls"]
)
async def test_single_attempt_rejects_non_complete_metadata_even_with_valid_json(
    monkeypatch, reason
):
    async def respond(request):
        return httpx.Response(200, json=completion(reason=reason), request=request)

    seen = mock_http(monkeypatch, respond)
    with capture_completions() as captured, pytest.raises(StructuredOutputError) as caught:
        await router(monkeypatch).aexecute_complex_task(
            "sys", "hi", Answer, "local-model", single_attempt=True
        )
    assert len(seen) == len(captured) == 1 and captured[0].completion_tokens == 8
    assert "PRIVATE_UNKNOWN_FINISH" not in str(caught.value)


@pytest.mark.parametrize(
    "kind", ["timeout", "server", "unsupported_schema", "rate_limit", "connection", "cancel"]
)
async def test_single_attempt_transport_failure_sends_one_actual_post(monkeypatch, kind):
    async def respond(request):
        if kind == "timeout":
            raise httpx.ReadTimeout("Offline structured timeout", request=request)
        if kind == "connection":
            raise httpx.ConnectError("Offline structured connection failure", request=request)
        if kind == "cancel":
            raise asyncio.CancelledError
        if kind == "unsupported_schema":
            return httpx.Response(
                400,
                json={
                    "error": {
                        "message": "Unsupported parameter: response_format of type json_schema is not supported.",
                        "type": "invalid_request_error",
                        "param": "response_format",
                        "code": "unsupported_value",
                    }
                },
                request=request,
            )
        if kind == "rate_limit":
            return httpx.Response(
                429, json={"error": {"message": "Offline rate limit"}}, request=request
            )
        return httpx.Response(
            503, json={"error": {"message": "Offline unavailable"}}, request=request
        )

    seen = mock_http(monkeypatch, respond)
    expected = {
        "timeout": Timeout,
        "server": ServiceUnavailableError,
        "unsupported_schema": BadRequestError,
        "rate_limit": RateLimitError,
        "connection": (APIConnectionError, InternalServerError),
        "cancel": asyncio.CancelledError,
    }
    with pytest.raises(expected[kind]):
        await router(monkeypatch, "json_schema").aexecute_complex_task(
            "sys", "hi", Answer, "local-model", single_attempt=True
        )
    assert len(seen) == 1
    assert json.loads(seen[0].content)["response_format"]["type"] == "json_schema"


async def test_single_attempt_cloud_disables_sdk_and_outer_transport_retries(monkeypatch):
    llm = router(monkeypatch)
    llm.provider, llm.api_key = "openai", "offline-placeholder"
    complete = AsyncMock(side_effect=TimeoutError("Offline cloud timeout"))
    monkeypatch.setattr(llm._get_litellm(), "acompletion", complete)
    monkeypatch.setattr("backend.core.llm_router.asyncio.sleep", AsyncMock())
    monkeypatch.setattr("backend.core.llm_router.target", lambda *_args: None)
    with pytest.raises(TimeoutError):
        await llm.aexecute_complex_task("sys", "hi", Answer, "gpt-4o-mini", single_attempt=True)
    assert complete.await_count == 1
    options = complete.call_args.kwargs
    assert "_single_attempt" not in options
    assert options["num_retries"] == options["max_retries"] == 0


async def test_default_complex_call_keeps_existing_blank_retry(monkeypatch):
    async def respond(request):
        value = completion("", reasoning="Reasoning only.") if len(seen) == 1 else completion()
        return httpx.Response(200, json=value, request=request)

    seen = mock_http(monkeypatch, respond)
    result = await router(monkeypatch).aexecute_complex_task("sys", "hi", Answer, "local-model")
    assert result == Answer(value=7) and len(seen) == 2


async def test_default_complex_call_keeps_existing_finish_policy(monkeypatch):
    async def respond(request):
        return httpx.Response(200, json=completion(reason="length"), request=request)

    seen = mock_http(monkeypatch, respond)
    result = await router(monkeypatch).aexecute_complex_task("sys", "hi", Answer, "local-model")
    assert result == Answer(value=7) and len(seen) == 1
