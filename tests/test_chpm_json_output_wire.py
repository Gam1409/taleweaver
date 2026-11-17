"""Selected portable output modes retain single-attempt wire and workflow guards."""

import json
from types import SimpleNamespace

import httpx
import pytest
from litellm import BadRequestError, Timeout

from backend.core.llm_tool_turn import InvalidToolTurnError
from backend.engine.chpm import integrated_protocol
from backend.engine.chpm.json_tool_port import JsonToolPort
from backend.engine.chpm.schema import Settings, Usage
from tests.test_chpm_json_output_policy import functions, request
from tests.test_chpm_json_tool_port import initial
from tests.test_llm_tool_turn import completion, mock_http, router


def configured_router(monkeypatch, mode):
    inner = router(monkeypatch)
    inner.model = "offline-model"
    inner.custom_response_format, inner.enable_thinking = mode, False
    return inner


@pytest.mark.parametrize("mode", ["prompt", "json_object", "json_schema"])
async def test_actual_router_wire_honors_selected_portable_mode_in_one_request(monkeypatch, mode):
    reply = {"requests": [request("inspect_self")]}

    async def respond(incoming):
        return httpx.Response(
            200,
            json=completion(calls=[], content=json.dumps(reply), reason="stop"),
            request=incoming,
        )

    inner = configured_router(monkeypatch, mode)
    seen = mock_http(monkeypatch, respond)

    turn = await JsonToolPort(inner).aexecute_tool_turn(
        initial(), functions("inspect_self"), inner.model
    )

    assert len(seen) == 1 and len(turn.calls) == 1
    body = json.loads(seen[0].content)
    assert {message["role"] for message in body["messages"]} == {"system", "user"}
    assert (
        not {"tools", "tool_choice", "_single_attempt", "num_retries", "max_retries"} & body.keys()
    )
    if mode == "prompt":
        assert "response_format" not in body
    else:
        assert body["response_format"]["type"] == mode


@pytest.mark.parametrize("mode", ["prompt", "json_object", "json_schema"])
@pytest.mark.parametrize(
    "outcome", ["timeout", "schema_rejected", "malformed", "unsupported_finish"]
)
async def test_failed_selected_format_never_triggers_a_port_retry(monkeypatch, mode, outcome):
    async def respond(incoming):
        if outcome == "timeout":
            raise httpx.ReadTimeout("Offline timeout", request=incoming)
        if outcome == "schema_rejected":
            return httpx.Response(
                400,
                json={
                    "error": {
                        "message": "Unsupported response schema",
                        "type": "invalid_request_error",
                    }
                },
                request=incoming,
            )
        return httpx.Response(
            200,
            json=completion(
                calls=[],
                content='{"requests":' if outcome == "malformed" else '{"requests":[]}',
                reason="stop" if outcome == "malformed" else "content_filter",
            ),
            request=incoming,
        )

    expected = {
        "schema_rejected": BadRequestError,
        "timeout": Timeout,
        "malformed": InvalidToolTurnError,
        "unsupported_finish": InvalidToolTurnError,
    }[outcome]
    inner = configured_router(monkeypatch, mode)
    seen = mock_http(monkeypatch, respond)

    with pytest.raises(expected):
        await JsonToolPort(inner).aexecute_tool_turn(
            initial(), functions("inspect_self"), inner.model
        )

    assert len(seen) == 1


@pytest.mark.parametrize("mode", ["prompt", "json_object", "json_schema"])
@pytest.mark.parametrize(
    ("requests", "code"),
    [
        (
            [request("approach"), request("set_pose"), request("submit_decision")],
            "too_many_requests",
        ),
        ([request("approach"), request("submit_decision")], "mixed_submission"),
        ([request("unavailable")], "unavailable_function"),
        ([], "missing_submission"),
    ],
)
async def test_ignored_remote_grammar_still_hits_existing_whole_response_guard(
    monkeypatch, mode, requests, code
):
    async def respond(incoming):
        return httpx.Response(
            200,
            json=completion(calls=[], content=json.dumps({"requests": requests}), reason="stop"),
            request=incoming,
        )

    inner = configured_router(monkeypatch, mode)
    seen = mock_http(monkeypatch, respond)
    usage = Usage()

    with pytest.raises(integrated_protocol.ProtocolError) as rejected:
        await integrated_protocol.read(
            SimpleNamespace(game_id="session"),
            Settings(mode="live", actor_ids=["NPC"], max_input_chars=64000),
            usage,
            initial(),
            functions("approach", "set_pose", "submit_decision"),
            seen_ids=set(),
            llm=JsonToolPort(inner),
        )

    assert rejected.value.code == code
    assert len(seen) == usage.calls == 1
