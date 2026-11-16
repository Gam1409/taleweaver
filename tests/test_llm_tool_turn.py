"""Native tool turns preserve the actual provider wire without opening network sockets."""

import asyncio
import json
from copy import deepcopy
from unittest.mock import AsyncMock

import httpx
import pytest

from backend.core import custom_openai
from backend.core.llm_completion_capture import capture_completions
from backend.core.llm_router import GameMasterLLM
from backend.models.user import User

ARGUMENTS = '{"path":"/memo","value":"Проверить 明日 \\"точно\\".","expected_revision":0}'
CALL = {
    "id": "call-new",
    "type": "function",
    "function": {"name": "notebook_write", "arguments": ARGUMENTS},
}
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "notebook_write",
            "description": "Write one value in the current private notebook.",
            "parameters": {"type": "object", "properties": {"value": {"type": "string"}}},
        },
    }
]
MESSAGES = [
    {"role": "system", "content": "Use only the declared notebook tools."},
    {"role": "user", "content": "Keep my own reminder."},
    {"role": "assistant", "content": None, "tool_calls": [{**CALL, "id": "call-old"}]},
    {"role": "tool", "tool_call_id": "call-old", "content": '{"status":"stale_revision"}'},
    {"role": "user", "content": "Use the current revision."},
]


def completion(*, calls=None, content=None, reason="tool_calls"):
    return {
        "id": "offline-tools",
        "object": "chat.completion",
        "created": 1,
        "model": "local-model",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": content,
                    "tool_calls": [CALL] if calls is None else calls,
                    "reasoning_content": "Provider continuation data.",
                },
                "finish_reason": reason,
            }
        ],
        "usage": {"prompt_tokens": 12, "completion_tokens": 8, "total_tokens": 20},
    }


def router(monkeypatch):
    monkeypatch.setattr(custom_openai, "validate_custom_url", lambda value: value)
    llm = GameMasterLLM(
        User(
            username="offline-tools",
            llm_settings={"custom_openai_url": "https://offline.invalid/v1"},
            encrypted_api_keys={},
        ),
        provider="custom_openai",
    )
    llm.max_tokens = 512
    llm.request_timeout = 2
    llm.enable_thinking = True
    return llm


def mock_http(monkeypatch, respond):
    seen = []

    async def send(_client, request, **_kwargs):
        seen.append(request)
        return await respond(request)

    def forbid_network(*_args, **_kwargs):
        raise AssertionError("The native tool test must not open a network socket.")

    monkeypatch.setattr(httpx.AsyncClient, "send", send)
    monkeypatch.setattr("socket.socket.connect", forbid_network)
    return seen


async def test_native_wire_preserves_tools_tool_role_null_content_and_raw_arguments(monkeypatch):
    async def respond(request):
        return httpx.Response(200, json=completion(), request=request)

    llm = router(monkeypatch)
    seen = mock_http(monkeypatch, respond)
    original = deepcopy((MESSAGES, TOOLS))
    with capture_completions() as captured:
        turn = await llm.aexecute_tool_turn(MESSAGES, TOOLS, "local-model", operation="chpm")
    body = json.loads(seen[0].content)
    assert len(seen) == 1
    expected_messages = deepcopy(MESSAGES)
    expected_messages[2].pop("content")
    assert body["messages"] == expected_messages and body["tools"] == TOOLS
    assert body["tool_choice"] == "auto" and body["max_tokens"] == 512
    assert "response_format" not in body and "thinking" not in body
    assert turn.assistant_message["content"] is None
    assert turn.assistant_message["tool_calls"][0]["id"] == "call-new"
    assert turn.assistant_message["reasoning_content"] == "Provider continuation data."
    assert turn.calls[0].arguments_raw == ARGUMENTS
    assert (turn.calls[0].id, turn.calls[0].name) == ("call-new", "notebook_write")
    assert turn.finish_reason == "tool_calls" and turn.usage["completion_tokens"] == 8
    assert captured[0].finish_reason == "tool_calls" and captured[0].completion_tokens == 8
    assert original == (MESSAGES, TOOLS) and llm.enable_thinking is True


async def test_native_port_accepts_text_completion_without_tool_calls(monkeypatch):
    async def respond(request):
        return httpx.Response(
            200, json=completion(calls=[], content="Ready.", reason="stop"), request=request
        )

    mock_http(monkeypatch, respond)
    turn = await router(monkeypatch).aexecute_tool_turn(MESSAGES, TOOLS, "local-model")
    assert turn.calls == () and turn.assistant_message["content"] == "Ready."
    assert turn.finish_reason == "stop"


@pytest.mark.parametrize("reason", [None, "stop", "tool_calls", "length", "max_tokens"])
async def test_native_port_preserves_compatible_terminal_reasons_and_usage(monkeypatch, reason):
    llm = router(monkeypatch)
    complete = AsyncMock(return_value=completion(reason=reason))
    monkeypatch.setattr(llm, "_acompletion_with_openrouter_fallback", complete)
    with capture_completions() as captured:
        result = await llm.aexecute_tool_turn(MESSAGES, TOOLS, "local-model")

    assert complete.await_count == 1 and result.finish_reason == reason
    assert result.calls[0].arguments_raw == ARGUMENTS
    assert result.usage["completion_tokens"] == captured[0].completion_tokens == 8
    assert captured[0].finish_reason == reason


@pytest.mark.parametrize(
    "reason",
    ["content_filter", "function_call", "PRIVATE_FINISH_CANARY", {}, [], 0, True],
)
async def test_native_port_rejects_untrusted_finish_reason_before_returning_calls(
    monkeypatch, reason
):
    from backend.core.llm_tool_turn import InvalidToolTurnError

    llm = router(monkeypatch)
    complete = AsyncMock(return_value=completion(reason=reason))
    monkeypatch.setattr(llm, "_acompletion_with_openrouter_fallback", complete)
    with capture_completions() as captured, pytest.raises(InvalidToolTurnError) as caught:
        await llm.aexecute_tool_turn(MESSAGES, TOOLS, "local-model")

    assert complete.await_count == 1
    assert captured[0].completion_tokens == 8
    assert "PRIVATE_FINISH_CANARY" not in str(caught.value)
    assert "finish reason" in str(caught.value) and len(str(caught.value)) <= 120


@pytest.mark.parametrize("reason", ["content_filter", "function_call", "unknown_terminal"])
async def test_actual_transport_cannot_normalize_a_failed_tool_completion_into_success(
    monkeypatch, reason
):
    from backend.core.llm_tool_turn import InvalidToolTurnError

    async def respond(request):
        return httpx.Response(200, json=completion(reason=reason), request=request)

    seen = mock_http(monkeypatch, respond)
    with capture_completions() as captured, pytest.raises(InvalidToolTurnError):
        await router(monkeypatch).aexecute_tool_turn(MESSAGES, TOOLS, "local-model")

    assert len(seen) == 1 and captured[0].completion_tokens == 8


@pytest.mark.parametrize(
    ("native", "expected"),
    [
        ("stop_sequence", "stop"),
        ("end_turn", "stop"),
        ("tool_use", "tool_calls"),
        ("COMPLETE", "stop"),
        ("eos_token", "stop"),
        ("eos", "stop"),
        ("STOP", "stop"),
        ("max_tokens", "length"),
        ("MAX_TOKENS", "length"),
        ("compaction", "length"),
    ],
)
async def test_known_provider_completion_aliases_are_retained_and_truncation_wins(
    monkeypatch, native, expected
):
    llm = router(monkeypatch)
    body = completion(reason="stop" if expected == "length" else expected)
    body["choices"][0]["provider_specific_fields"] = {"native_finish_reason": native}
    monkeypatch.setattr(llm, "_acompletion_with_openrouter_fallback", AsyncMock(return_value=body))

    result = await llm.aexecute_tool_turn(MESSAGES, TOOLS, "local-model")

    assert result.finish_reason == expected and result.calls[0].arguments_raw == ARGUMENTS


@pytest.mark.parametrize(
    "native",
    [
        "error",
        "ERROR",
        "network_error",
        "FINISH_REASON_UNSPECIFIED",
        "MALFORMED_FUNCTION_CALL",
        {},
        [],
    ],
)
async def test_normalized_error_or_malformed_provider_flags_are_rejected(monkeypatch, native):
    from backend.core.llm_tool_turn import InvalidToolTurnError

    llm = router(monkeypatch)
    body = completion(reason="stop")
    body["choices"][0]["provider_specific_fields"] = {"native_finish_reason": native}
    monkeypatch.setattr(llm, "_acompletion_with_openrouter_fallback", AsyncMock(return_value=body))

    with pytest.raises(InvalidToolTurnError):
        await llm.aexecute_tool_turn(MESSAGES, TOOLS, "local-model")


@pytest.mark.parametrize("kind", ["timeout", "server", "cancel"])
async def test_native_transport_failures_never_retry_or_become_unsupported(monkeypatch, kind):
    from backend.core.llm_tool_turn import NativeToolsUnsupportedError

    async def respond(request):
        if kind == "timeout":
            raise httpx.ReadTimeout("Offline scripted timeout", request=request)
        if kind == "cancel":
            raise asyncio.CancelledError
        return httpx.Response(
            503, json={"error": {"message": "Offline unavailable"}}, request=request
        )

    seen = mock_http(monkeypatch, respond)
    expected = asyncio.CancelledError if kind == "cancel" else Exception
    with pytest.raises(expected) as caught:
        await router(monkeypatch).aexecute_tool_turn(MESSAGES, TOOLS, "local-model")
    assert not isinstance(caught.value, NativeToolsUnsupportedError)
    assert len(seen) == 1


async def test_unsupported_adapter_is_rejected_before_transport_even_with_global_drop(monkeypatch):
    from backend.core.llm_tool_turn import NativeToolsUnsupportedError

    llm = router(monkeypatch)
    monkeypatch.setattr(
        llm._get_litellm(), "get_supported_openai_params", lambda **_kwargs: ["max_tokens"]
    )

    async def unexpected(_request):
        raise AssertionError("An unsupported adapter must not send inference.")

    seen = mock_http(monkeypatch, unexpected)
    with pytest.raises(NativeToolsUnsupportedError):
        await llm.aexecute_tool_turn(MESSAGES, TOOLS, "local-model")
    assert seen == []


async def test_native_arguments_are_not_parsed_or_repaired_by_the_shared_port(monkeypatch):
    malformed = '{"value":1,"value":2'

    async def respond(request):
        raw_call = {**CALL, "function": {**CALL["function"], "arguments": malformed}}
        return httpx.Response(200, json=completion(calls=[raw_call]), request=request)

    mock_http(monkeypatch, respond)
    turn = await router(monkeypatch).aexecute_tool_turn(MESSAGES, TOOLS, "local-model")
    assert turn.calls[0].arguments_raw == malformed


async def test_native_cloud_transport_is_single_attempt_while_legacy_retry_is_unchanged(
    monkeypatch,
):
    llm = router(monkeypatch)
    llm.provider = "openai"
    llm.api_key = "offline-placeholder"
    complete = AsyncMock(side_effect=TimeoutError("Offline cloud timeout"))
    monkeypatch.setattr(llm._get_litellm(), "acompletion", complete)
    monkeypatch.setattr("backend.core.llm_router.asyncio.sleep", AsyncMock())
    monkeypatch.setattr("backend.core.llm_router.target", lambda *_args: None)
    with pytest.raises(TimeoutError):
        await llm.aexecute_tool_turn(MESSAGES, TOOLS, "gpt-4o-mini")
    assert complete.await_count == 1
    kwargs = complete.call_args.kwargs
    assert "_single_attempt" not in kwargs and kwargs["num_retries"] == kwargs["max_retries"] == 0
    complete.reset_mock()
    with pytest.raises(TimeoutError):
        await llm._acompletion_with_openrouter_fallback({"model": "gpt-4o-mini", "messages": []})
    assert complete.await_count == 4


@pytest.mark.parametrize("invalid", ["", {}, "not-a-list", 1])
async def test_malformed_tool_envelope_is_not_treated_as_ready(monkeypatch, invalid):
    from backend.core.llm_tool_turn import InvalidToolTurnError

    llm = router(monkeypatch)
    body = completion()
    body["choices"][0]["message"]["tool_calls"] = invalid
    complete = AsyncMock(return_value=body)
    monkeypatch.setattr(llm, "_acompletion_with_openrouter_fallback", complete)
    with pytest.raises(InvalidToolTurnError):
        await llm.aexecute_tool_turn(MESSAGES, TOOLS, "local-model")
    assert complete.await_count == 1
