"""Required action rounds enforce provider choice and reject ignored constraints locally."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from jsonschema import Draft202012Validator

from backend.core.llm_tool_turn import InvalidToolTurnError
from backend.engine.chpm import inference
from backend.engine.chpm.errors import InferenceUnavailableError, RecoverableChpmError
from backend.engine.chpm.json_tool_port import JsonToolPort
from backend.engine.chpm.schema import Settings, Usage
from backend.engine.npc_actions.tool_schema import definitions
from tests.test_chpm_json_output_policy import ConfiguredTextModel
from tests.test_chpm_json_tool_port import initial
from tests.test_deepseek_thinking import router as deepseek_router
from tests.test_llm_tool_turn import completion, mock_http, router

TAKE = {"name": "take_item", "arguments": {"item_id": "CUP"}}
TOOLS = definitions({"take_item"})
HOST = SimpleNamespace(game_id="session")


def settings():
    return Settings(mode="live", actor_ids=["NPC"], tool_profile="deepseek", max_input_chars=64000)


@pytest.mark.parametrize("outcome", ["applied_call", "no_calls", "unknown_tool", "unsupported"])
async def test_native_required_round_preserves_parameter_and_never_retries(monkeypatch, outcome):
    async def respond(incoming):
        if outcome == "unsupported":
            return httpx.Response(
                400,
                json={
                    "error": {
                        "message": "Unsupported tool_choice value",
                        "type": "invalid_request_error",
                    }
                },
                request=incoming,
            )
        calls = (
            []
            if outcome == "no_calls"
            else [
                {
                    "id": "c1",
                    "type": "function",
                    "function": {
                        "name": "inspect_scene" if outcome == "unknown_tool" else TAKE["name"],
                        "arguments": json.dumps(TAKE["arguments"]),
                    },
                }
            ]
        )
        return httpx.Response(
            200,
            json=completion(
                calls=calls,
                content=None if calls else "I take it.",
                reason="tool_calls" if calls else "stop",
            ),
            request=incoming,
        )

    model, usage = router(monkeypatch), Usage()
    model.model = "offline-model"
    seen = mock_http(monkeypatch, respond)
    task = inference.tool_request(
        HOST, settings(), usage, initial(), TOOLS, llm=model, require_tools=True
    )
    if outcome == "applied_call":
        result = await task
        assert [(entry.name, json.loads(entry.arguments_raw)) for entry in result.calls] == [
            (TAKE["name"], TAKE["arguments"])
        ]
    elif outcome == "unsupported":
        with pytest.raises(InferenceUnavailableError):
            await task
    else:
        with pytest.raises(inference.ToolEnvelopeError) as denied:
            await task
        assert denied.value.code == (
            "required_tool_missing" if outcome == "no_calls" else "unavailable_function"
        )
        assert denied.value.call_ids == (() if outcome == "no_calls" else ("c1",))
    assert len(seen) == usage.calls == 1
    assert json.loads(seen[0].content)["tool_choice"] == "required"


@pytest.mark.parametrize("mode", ["json_schema", "json_object", "prompt"])
async def test_portable_required_round_counts_exact_wire_and_permits_only_offered_calls(mode):
    raw = json.dumps({"requests": [TAKE]})
    inner = ConfiguredTextModel(mode, [raw])
    port, usage = JsonToolPort(inner), Usage()
    result = await inference.tool_request(
        HOST, settings(), usage, initial(), TOOLS, llm=port, require_tools=True
    )
    assert [entry.name for entry in result.calls] == ["take_item"]
    assert usage.calls == len(inner.calls) == 1
    prompt, payload, _, options = inner.calls[0]
    assert "[] when ready" not in prompt
    assert "at least one" in prompt.lower()
    response_format = options["response_format"]
    length = len(prompt) + len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    if response_format:
        length += len(json.dumps(response_format, ensure_ascii=False, separators=(",", ":")))
    assert usage.input_chars == length == port.input_size(initial(), TOOLS, require_tools=True)
    if mode == "json_schema":
        validator = Draft202012Validator(response_format["json_schema"]["schema"])
        assert validator.is_valid(json.loads(raw))
        assert not validator.is_valid({"requests": []})
        assert not validator.is_valid({"requests": [{"name": "inspect_scene", "arguments": {}}]})


@pytest.mark.parametrize(
    "raw,code",
    [
        ('{"requests":[]}', "required_tool_missing"),
        ('{"requests":[{"name":"submit_decision","arguments":{}}]}', "unavailable_function"),
        ('{"requests":[{"name":"inspect_scene","arguments":{}}]}', "unavailable_function"),
        ('{"choice":"words only"}', "missing_requests"),
    ],
)
async def test_portable_required_guard_checks_actual_reply_when_grammar_is_ignored(raw, code):
    inner = ConfiguredTextModel("json_schema", [raw])
    with pytest.raises(InvalidToolTurnError) as denied:
        await JsonToolPort(inner).aexecute_tool_turn(
            initial(), TOOLS, inner.model, tool_choice="required"
        )
    assert denied.value.code == code and len(inner.calls) == 1
    if code == "unavailable_function":
        assert len(denied.value.call_ids) == 1


@pytest.mark.parametrize(
    "catalog",
    [
        [],
        [
            {
                "type": "function",
                "function": {"name": "submit_decision", "parameters": {"type": "object"}},
            }
        ],
    ],
)
async def test_invalid_required_catalog_does_not_reserve_a_call(catalog):
    inner, usage = ConfiguredTextModel("json_schema"), Usage()
    with pytest.raises(RecoverableChpmError):
        await inference.tool_request(
            HOST, settings(), usage, initial(), catalog, llm=JsonToolPort(inner), require_tools=True
        )
    assert not inner.calls and not usage.calls


def test_installed_deepseek_adapter_preserves_required_choice_for_the_actual_function_tools(
    monkeypatch,
):
    from litellm.llms.deepseek.chat.transformation import DeepSeekChatConfig

    from backend.core.llm_tool_turn import _request_kwargs, ensure_tools_supported

    model = deepseek_router(monkeypatch, enabled=False)
    ensure_tools_supported(model, model.model)
    wire = _request_kwargs(model, initial(), TOOLS, model.model, "required")
    adapter = DeepSeekChatConfig()
    options = adapter.map_openai_params(
        {field: wire[field] for field in ("tool_choice", "tools", "thinking")},
        {},
        model.model,
        False,
    )
    prepared = adapter.transform_request(model.model, initial(), options, {}, {})
    assert prepared["tool_choice"] == "required" and prepared["tools"] == TOOLS
    assert prepared["thinking"] == {"type": "disabled"}


async def test_anthropic_adapter_cannot_downgrade_a_required_round_with_global_drop(monkeypatch):
    from backend.core.llm_tool_turn import NativeToolsUnsupportedError

    model = router(monkeypatch)
    model.provider, model.api_base = "anthropic", None
    model.model = "claude-3-5-sonnet-latest"
    adapter = model._get_litellm()
    monkeypatch.setattr(adapter, "drop_params", True)
    monkeypatch.setitem(
        adapter.model_cost,
        model.model,
        {**adapter.model_cost.get(model.model, {}), "supports_forced_tool_use": False},
    )
    complete = AsyncMock(return_value=completion())
    monkeypatch.setattr(model, "_acompletion_with_openrouter_fallback", complete)
    with pytest.raises(NativeToolsUnsupportedError, match="required"):
        await model.aexecute_tool_turn(initial(), TOOLS, model.model, tool_choice="required")
    complete.assert_not_awaited()
    await model.aexecute_tool_turn(initial(), TOOLS, model.model, tool_choice="auto")
    complete.assert_awaited_once()
