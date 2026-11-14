"""The portable JSON representation feeds the same native tool contracts and feedback."""

import json
from copy import deepcopy

import pytest
from jsonschema import Draft202012Validator
from litellm import InternalServerError

from backend.core.llm_tool_turn import InvalidToolTurnError
from backend.engine.chpm.native_tool_contracts import parse_call, tool_definitions


class TextModel:
    def __init__(self, replies):
        self.replies, self.calls = list(replies), []
        self.max_tokens, self.enable_thinking, self.request_timeout = 1200, True, 15
        self.model, self.provider = "offline-model", "offline-provider"

    async def aexecute_simple_task(self, system, payload, model, **kwargs):
        self.calls.append((system, json.loads(payload), model, kwargs))
        reply = self.replies.pop(0)
        if isinstance(reply, BaseException):
            raise reply
        return reply


def initial():
    return [
        {"role": "system", "content": "This is this NPC's own notebook, not world evidence."},
        {
            "role": "user",
            "content": json.dumps(
                {
                    "observer_id": "KEEPER",
                    "personal_notebook": {"revision": 0},
                    "remaining_rounds": 2,
                    "observation": {"player_request": "I might remember this later."},
                    "previous_lookups": [],
                }
            ),
        },
    ]


async def test_port_uses_plain_json_values_and_canonical_tool_history():
    from backend.engine.chpm.json_tool_port import JsonToolPort

    note = {"自由": [None, True, 'Проверить \\"точно\\" 明日'], "npc_id": "a subjective quote"}
    inner = TextModel(
        [
            json.dumps(
                {
                    "requests": [
                        {
                            "name": "notebook_write",
                            "arguments": {"path": "/memo", "value": note, "expected_revision": 0},
                        }
                    ]
                },
                ensure_ascii=False,
            )
        ]
    )
    port = JsonToolPort(inner)
    messages, functions = initial(), tool_definitions()
    original = deepcopy((messages, functions))
    turn = await port.aexecute_tool_turn(messages, functions, port.model, operation="chpm")
    assert len(inner.calls) == 1 and original == (messages, functions)
    assert inner.calls[0][3] == {"operation": "chpm"}
    assert "value_json" not in json.dumps(inner.calls[0][1]["functions"])
    assert turn.assistant_message["content"] is None and len(turn.calls) == 1
    assert turn.assistant_message["tool_calls"][0]["id"] == turn.calls[0].id
    request = parse_call(turn.calls[0].name, turn.calls[0].arguments_raw)
    assert json.loads(request.value_json) == note


async def test_round_two_contains_correlated_error_and_current_host_metadata():
    from backend.engine.chpm.json_tool_port import JsonToolPort

    inner = TextModel(
        [
            '{"requests":[{"name":"notebook_read","arguments":{"path":"/missing"}}]}',
            '{"requests":[]}',
        ]
    )
    port = JsonToolPort(inner)
    messages, functions = initial(), tool_definitions()
    first = await port.aexecute_tool_turn(messages, functions, port.model)
    messages.extend(
        [
            first.assistant_message,
            {
                "role": "tool",
                "tool_call_id": first.calls[0].id,
                "content": '{"status":"missing_path","revision":3}',
            },
            {
                "role": "user",
                "content": '{"host_context_update":{"remaining_rounds":1,"personal_notebook":{"revision":3}}}',
            },
        ]
    )
    second = await port.aexecute_tool_turn(messages, functions, port.model)
    payload = inner.calls[1][1]
    assert second.calls == ()
    assert payload["personal_notebook"]["revision"] == 3 and payload["remaining_rounds"] == 1
    assert payload["observation"]["player_request"] == "I might remember this later."
    assert payload["conversation"][-2]["tool_call_id"] == first.calls[0].id
    assert payload["previous_lookups"][0]["results"][0]["status"] == "missing_path"


async def test_legacy_bridge_strictly_decodes_values_and_edit_operations():
    from backend.engine.chpm.json_tool_port import JsonToolPort

    legacy = {
        "purpose": "Keep a private thought.",
        "requests": [
            {
                "tool": "notebook_write",
                "path": "/memo",
                "value_json": json.dumps({"note": "A possibility."}),
                "expected_revision": 0,
            },
            {
                "tool": "notebook_edit",
                "expected_revision": 1,
                "operations": [
                    {"op": "replace", "path": "/memo", "value_json": "null"},
                    {"op": "remove", "path": "/old", "value_json": None},
                ],
            },
        ],
    }
    turn = await JsonToolPort(TextModel([json.dumps(legacy)])).aexecute_tool_turn(
        initial(), tool_definitions(), "offline"
    )
    assert len({call.id for call in turn.calls}) == 2
    assert json.loads(turn.calls[0].arguments_raw)["value"] == {"note": "A possibility."}
    assert json.loads(turn.calls[1].arguments_raw)["operations"] == [
        {"op": "replace", "path": "/memo", "value": None},
        {"op": "remove", "path": "/old"},
    ]


@pytest.mark.parametrize(
    "raw",
    [
        '{"requests":',
        '{"requests":[],"requests":[]}',
        '{"requests":{}}',
        '{"requests":[{"name":"notebook_write","arguments":{"value":1,"value":2}}]}',
        '{"requests":[{"tool":"notebook_write","value_json":"{\\"x\\":1,\\"x\\":2}"}]}',
        '{"requests":[{"name":"notebook_write","arguments":{"value":NaN}}]}',
        '{"requests":[{"name":"notebook_write","arguments":{"value":1e999}}]}',
    ],
)
async def test_outer_format_errors_are_visible_without_retry(raw):
    from backend.engine.chpm.json_tool_port import JsonToolPort

    inner = TextModel([raw])
    with pytest.raises(InvalidToolTurnError):
        await JsonToolPort(inner).aexecute_tool_turn(initial(), tool_definitions(), "offline")
    assert len(inner.calls) == 1


async def test_proxy_limits_and_exact_input_size():
    from backend.engine.chpm.json_tool_port import JsonToolPort, compose

    inner = TextModel(['{"requests":[]}'])
    port = JsonToolPort(inner)
    port.max_tokens, port.enable_thinking, port.request_timeout = 512, False, 9
    assert (inner.max_tokens, inner.enable_thinking, inner.request_timeout) == (512, False, 9)
    messages, functions = initial(), tool_definitions()
    system, payload = compose(messages, functions)
    assert port.input_size(messages, functions) == len(system) + len(payload)
    assert port.provider == inner.provider


async def test_transport_error_is_not_a_format_error_or_automatic_retry():
    from backend.engine.chpm.json_tool_port import JsonToolPort

    inner = TextModel([TimeoutError("Offline timeout")])
    with pytest.raises(TimeoutError):
        await JsonToolPort(inner).aexecute_tool_turn(initial(), tool_definitions(), "offline")
    assert len(inner.calls) == 1


async def test_real_router_json_wire_uses_only_text_messages_and_single_attempt(monkeypatch):
    import httpx

    from backend.engine.chpm.json_tool_port import JsonToolPort
    from tests.test_llm_tool_turn import completion, mock_http, router

    plan = '{"requests":[{"name":"notebook_write","arguments":{"path":"/memo","value":"A thought, not evidence.","expected_revision":0}}]}'

    async def respond(request):
        return httpx.Response(
            200, json=completion(calls=[], content=plan, reason="stop"), request=request
        )

    inner = router(monkeypatch)
    inner.enable_thinking = False
    seen = mock_http(monkeypatch, respond)
    turn = await JsonToolPort(inner).aexecute_tool_turn(
        initial(), tool_definitions(), "offline-model"
    )
    body = json.loads(seen[0].content)
    assert len(seen) == 1 and len(turn.calls) == 1
    assert {message["role"] for message in body["messages"]} == {"system", "user"}
    assert not {"tools", "tool_choice", "response_format", "_single_attempt"} & set(body)
    assert body["max_tokens"] == 512
    assert json.loads(body["messages"][1]["content"])["functions"]
    assert (
        json.loads(parse_call(turn.calls[0].name, turn.calls[0].arguments_raw).value_json)
        == "A thought, not evidence."
    )


async def test_json_cloud_port_never_uses_legacy_transient_retries(monkeypatch):
    from unittest.mock import AsyncMock

    from backend.engine.chpm.json_tool_port import JsonToolPort
    from tests.test_llm_tool_turn import router

    inner = router(monkeypatch)
    inner.provider, inner.api_key = "openai", "offline-placeholder"
    complete = AsyncMock(side_effect=TimeoutError("Offline JSON timeout"))
    monkeypatch.setattr(inner._get_litellm(), "acompletion", complete)
    monkeypatch.setattr("backend.core.llm_router.target", lambda *_args: None)
    with pytest.raises(TimeoutError):
        await JsonToolPort(inner).aexecute_tool_turn(initial(), tool_definitions(), "gpt-4o-mini")
    assert complete.await_count == 1
    kwargs = complete.call_args.kwargs
    assert "_single_attempt" not in kwargs and kwargs["num_retries"] == kwargs["max_retries"] == 0


async def test_truncated_json_response_keeps_completion_marker_without_decoding_partial_calls():
    from backend.core.llm_completion_capture import record_completion
    from backend.engine.chpm.json_tool_port import JsonToolPort

    class TruncatedModel(TextModel):
        async def aexecute_simple_task(self, system, payload, model, **kwargs):
            record_completion(
                {"choices": [{"finish_reason": "length"}], "usage": {"completion_tokens": 512}}
            )
            return await super().aexecute_simple_task(system, payload, model, **kwargs)

    inner = TruncatedModel(['{"requests":['])
    turn = await JsonToolPort(inner).aexecute_tool_turn(initial(), tool_definitions(), "offline")
    assert turn.calls == () and turn.finish_reason == "length"
    assert turn.usage == {"completion_tokens": 512} and len(inner.calls) == 1


@pytest.mark.parametrize(
    ("native", "expected_error"),
    [
        ("content_filter", InvalidToolTurnError),
        ("PRIVATE_UNKNOWN_TERMINAL", InvalidToolTurnError),
        ([], InternalServerError),
        ({}, InternalServerError),
        (0, InvalidToolTurnError),
        (False, InvalidToolTurnError),
    ],
)
async def test_portable_json_rejects_untrusted_native_finish_before_returning_operations(
    monkeypatch, native, expected_error
):
    import httpx

    from backend.engine.chpm.json_tool_port import JsonToolPort
    from tests.test_llm_tool_turn import completion, mock_http, router

    plan = '{"requests":[{"name":"notebook_write","arguments":{"path":"/memo","value":"Must not be applied.","expected_revision":0}}]}'

    async def respond(request):
        body = completion(calls=[], content=plan, reason=native)
        return httpx.Response(200, json=body, request=request)

    inner = router(monkeypatch)
    inner.enable_thinking = False
    seen = mock_http(monkeypatch, respond)
    with pytest.raises(expected_error) as caught:
        await JsonToolPort(inner).aexecute_tool_turn(initial(), tool_definitions(), "offline-model")
    assert len(seen) == 1 and "PRIVATE_UNKNOWN_TERMINAL" not in str(caught.value)


@pytest.mark.parametrize("native", ["length", "max_tokens", "MAX_TOKENS", "compaction"])
async def test_portable_json_native_truncation_never_returns_complete_looking_calls(
    monkeypatch, native
):
    import httpx

    from backend.engine.chpm.json_tool_port import JsonToolPort
    from tests.test_llm_tool_turn import completion, mock_http, router

    plan = '{"requests":[{"name":"notebook_delete","arguments":{"path":"","expected_revision":0}}]}'

    async def respond(request):
        body = completion(calls=[], content=plan, reason=native)
        return httpx.Response(200, json=body, request=request)

    seen = mock_http(monkeypatch, respond)
    turn = await JsonToolPort(router(monkeypatch)).aexecute_tool_turn(
        initial(), tool_definitions(), "offline-model"
    )
    assert len(seen) == 1 and turn.calls == () and turn.finish_reason == "length"


def resolve(value, payload):
    if isinstance(value, list):
        return [resolve(item, payload) for item in value]
    if not isinstance(value, dict):
        return value
    if set(value) == {"$ref"}:
        target = payload
        for part in value["$ref"].removeprefix("#/").split("/"):
            target = target[int(part)] if isinstance(target, list) else target[part]
        return resolve(target, payload)
    return {key: resolve(item, payload) for key, item in value.items()}


def test_compose_keeps_sources_instructions_and_feedback_exactly_once():
    from backend.engine.chpm.json_tool_port import compose

    messages = initial()
    messages[0]["content"] += " UNIQUE_SYSTEM_AUTHORITY"
    context = json.loads(messages[1]["content"])
    context["observation"]["player_request"] = "UNIQUE_SOURCE_QUOTE"
    messages[1]["content"] = json.dumps(context)
    raw = '{"tool":"UNTRUSTED_ARGUMENT_TOOL","value":"UNIQUE_PRIVATE_ARGUMENT"}'
    messages.extend(
        [
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call-1",
                        "type": "function",
                        "function": {"name": "UNTRUSTED_PRIVATE_NAME", "arguments": raw},
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "call-1",
                "content": '{"status":"invalid_arguments","message":"UNIQUE_PRIVATE_ERROR"}',
            },
            {
                "role": "user",
                "content": '{"host_context_update":{"personal_notebook":{"revision":3},"remaining_rounds":1,"extra_context":"UNIQUE_EXTRA_CONTEXT"}}',
            },
        ]
    )
    system, serialized = compose(messages, tool_definitions())
    payload = json.loads(serialized)
    for literal in (
        "UNIQUE_SYSTEM_AUTHORITY",
        "UNIQUE_SOURCE_QUOTE",
        "UNIQUE_PRIVATE_ARGUMENT",
        "UNIQUE_PRIVATE_ERROR",
        "UNIQUE_EXTRA_CONTEXT",
        "UNTRUSTED_PRIVATE_NAME",
    ):
        assert (system + serialized).count(literal) == 1
    request = payload["previous_lookups"][0]["requests"][0]
    assert request["tool"] == "unknown_tool"
    assert "UNTRUSTED_ARGUMENT_TOOL" not in json.dumps(request)
    original_call = resolve({"$ref": request["call_ref"]}, payload)
    assert original_call["function"]["arguments"] == raw
    tool_message = next(message for message in payload["conversation"] if message["role"] == "tool")
    assert (
        resolve({"$ref": tool_message["content_ref"]}, payload)["message"] == "UNIQUE_PRIVATE_ERROR"
    )
    assert (
        payload["conversation"][0]["historical_host_overrides"]["personal_notebook"]["revision"]
        == 0
    )


@pytest.mark.parametrize(
    "name,arguments",
    [
        ("search_memory", {"argument": ""}),
        ("search_memory", {"argument": "shared records"}),
        ("search_memory", {"argument": "a" * 161}),
        ("notebook_read", {"path": "", "offset": 0, "limit": 1400}),
        ("notebook_read", {"limit": 1401}),
        ("notebook_read", {"offset": True}),
        (
            "notebook_write",
            {"path": "", "expected_revision": 0, "value": {"freely_chosen": {"title": None}}},
        ),
        ("notebook_write", {"path": "", "expected_revision": -1, "value": None}),
        ("notebook_write", {"path": "", "value": None}),
        ("notebook_info", {"npc_id": "other"}),
        (
            "notebook_edit",
            {
                "expected_revision": 0,
                "operations": [{"op": "replace", "path": "/x", "value": None}],
            },
        ),
        ("notebook_edit", {"expected_revision": 0, "operations": []}),
    ],
)
def test_compact_function_schemas_keep_the_original_argument_constraints(name, arguments):
    from backend.engine.chpm.json_tool_port import compose

    tools = tool_definitions()
    _, serialized = compose(initial(), tools)
    payload = json.loads(serialized)
    original = next(
        tool["function"]["parameters"] for tool in tools if tool["function"]["name"] == name
    )
    compact = next(item["parameters"] for item in payload["functions"] if item["name"] == name)
    Draft202012Validator.check_schema(resolve(compact, payload))
    assert Draft202012Validator(resolve(compact, payload)).is_valid(
        arguments
    ) == Draft202012Validator(original).is_valid(arguments)
