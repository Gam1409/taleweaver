"""Canonical argument constraints reach one portable request within existing admission."""

import json
from types import SimpleNamespace

import httpx
import pytest
from jsonschema import Draft202012Validator

from backend.core.llm_structured_execution import input_characters
from backend.engine.chpm import inference, json_tool_output
from backend.engine.chpm.errors import RecoverableChpmError
from backend.engine.chpm.json_tool_port import JsonToolPort, compose
from backend.engine.chpm.native_tool_contracts import tool_definitions
from backend.engine.chpm.schema import Settings, Usage
from tests.test_chpm_json_output_policy import ConfiguredTextModel
from tests.test_chpm_json_output_wire import configured_router
from tests.test_chpm_json_tool_port import initial
from tests.test_chpm_portable_argument_schema import envelope, offered, proposal
from tests.test_llm_tool_turn import completion, mock_http


def prepared(inner, messages, tools):
    system, payload = compose(messages, tools)
    return {
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": payload}],
        "response_format": json_tool_output.selected(inner, tools),
    }


@pytest.mark.parametrize("mode", ["prompt", "json_object", "json_schema"])
async def test_full_argument_schema_keeps_prompt_bytes_and_single_attempt_transport(
    monkeypatch, mode
):
    reply = envelope("submit_decision", proposal())

    async def respond(incoming):
        return httpx.Response(
            200,
            json=completion(calls=[], content=json.dumps(reply), reason="stop"),
            request=incoming,
        )

    inner = configured_router(monkeypatch, mode)
    seen = mock_http(monkeypatch, respond)
    tools, messages = offered(), initial()
    expected = prepared(inner, messages, tools)
    turn = await JsonToolPort(inner).aexecute_tool_turn(messages, tools, inner.model)

    assert len(seen) == len(turn.calls) == 1
    body = json.loads(seen[0].content)
    assert body["messages"] == expected["messages"]
    assert "tools" not in body and "tool_choice" not in body
    if mode == "prompt":
        assert "response_format" not in body
    elif mode == "json_object":
        assert body["response_format"] == {"type": "json_object"}
    else:
        schema = body["response_format"]["json_schema"]["schema"]
        validator = Draft202012Validator(schema)
        assert validator.is_valid(reply)
        assert not validator.is_valid(envelope("submit_decision", {"choice": proposal()["choice"]}))


async def test_full_schema_fits_an_exact_64000_prepared_request_and_remains_in_admission(
    monkeypatch,
):
    reply = envelope("submit_decision", proposal())

    async def respond(incoming):
        return httpx.Response(
            200,
            json=completion(calls=[], content=json.dumps(reply), reason="stop"),
            request=incoming,
        )

    inner = configured_router(monkeypatch, "json_schema")
    seen = mock_http(monkeypatch, respond)
    port, messages, tools = JsonToolPort(inner), initial(), offered()
    context = json.loads(messages[1]["content"])
    context["padding"] = ""
    messages[1]["content"] = json.dumps(context)
    missing = 64000 - input_characters(prepared(inner, messages, tools))
    assert missing > 0
    context["padding"] = "x" * missing
    messages[1]["content"] = json.dumps(context)
    assert input_characters(prepared(inner, messages, tools)) == 64000
    usage = Usage()
    await inference.tool_request(
        SimpleNamespace(game_id="session"),
        Settings(mode="live", actor_ids=["NPC"], agent_steps=1, max_input_chars=64000),
        usage,
        messages,
        tools,
        llm=port,
    )
    assert input_characters(json.loads(seen[0].content)) == 64000
    assert usage.calls == len(seen) == 1

    blocked = Usage()
    with pytest.raises(RecoverableChpmError, match="input exceeds"):
        await inference.tool_request(
            SimpleNamespace(game_id="session"),
            Settings(
                mode="live",
                actor_ids=["NPC"],
                agent_steps=1,
                max_input_chars=port.input_size(messages, tools) - 1,
            ),
            blocked,
            messages,
            tools,
            llm=port,
        )
    assert blocked.calls == 0 and len(seen) == 1


@pytest.mark.parametrize("mode", ["prompt", "json_object"])
async def test_existing_8000_character_modes_keep_their_current_budget_and_prompt(mode):
    inner = ConfiguredTextModel(mode)
    port, messages = JsonToolPort(inner), initial()
    tools = tool_definitions(False, available_lookups={"inspect_self"})
    context = json.loads(messages[1]["content"])
    context["padding"] = ""
    messages[1]["content"] = json.dumps(context)
    context["padding"] = "x" * (8000 - port.input_size(messages, tools))
    messages[1]["content"] = json.dumps(context)
    assert port.input_size(messages, tools) == 8000
    original = compose(messages, tools)
    usage = Usage()
    await inference.tool_request(
        SimpleNamespace(game_id="session"),
        Settings(mode="live", actor_ids=["NPC"], agent_steps=1, max_input_chars=8000),
        usage,
        messages,
        tools,
        llm=port,
    )
    assert usage.calls == 1 and usage.input_chars == 8000
    assert inner.calls[0][0] == original[0]
    assert inner.calls[0][1] == json.loads(original[1])
