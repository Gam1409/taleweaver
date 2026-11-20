"""Portable functions honor selected output capabilities without adding dispatches."""

import json
from types import SimpleNamespace

import pytest
from jsonschema import Draft202012Validator

from backend.engine.chpm import inference
from backend.engine.chpm.errors import RecoverableChpmError
from backend.engine.chpm.json_tool_port import JsonToolPort, compose
from backend.engine.chpm.schema import Settings, Usage
from tests.test_chpm_json_tool_port import TextModel, initial


class ConfiguredTextModel(TextModel):
    def __init__(self, mode, replies=None):
        super().__init__(replies or ['{"requests":[]}'])
        self.provider = "custom_openai"
        self.custom_response_format = mode

    async def aexecute_simple_task(
        self, system, payload, model, *, response_format=None, single_attempt=False, **kwargs
    ):
        return await super().aexecute_simple_task(
            system,
            payload,
            model,
            response_format=response_format,
            single_attempt=single_attempt,
            **kwargs,
        )


def functions(*names):
    return [
        {
            "type": "function",
            "function": {
                "name": name,
                "description": "An offered host function.",
                "parameters": {"type": "object"},
            },
        }
        for name in names
    ]


@pytest.mark.parametrize("mode", ["json_object", "json_schema"])
async def test_explicit_custom_output_policy_reaches_the_single_portable_request(mode):
    inner = ConfiguredTextModel(mode)
    await JsonToolPort(inner).aexecute_tool_turn(initial(), functions("inspect_self"), inner.model)

    assert len(inner.calls) == 1
    options = inner.calls[0][3]
    assert options["single_attempt"] is True
    assert options["response_format"]["type"] == mode


@pytest.mark.parametrize("mode", ["json_object", "json_schema"])
async def test_selected_format_counts_against_input_budget_before_dispatch(mode):
    inner = ConfiguredTextModel(mode)
    port = JsonToolPort(inner)
    offered = functions("inspect_self")
    messages = initial()
    payload = json.loads(messages[1]["content"])
    payload["padding"] = ""
    messages[1]["content"] = json.dumps(payload)
    prompt, content = compose(messages, offered)
    payload["padding"] = "x" * (8000 - len(prompt) - len(content))
    messages[1]["content"] = json.dumps(payload)
    assert sum(map(len, compose(messages, offered))) == 8000

    settings = Settings(mode="live", actor_ids=["NPC"], agent_steps=1, max_input_chars=8000)
    usage = Usage()
    with pytest.raises(RecoverableChpmError, match="input exceeds"):
        await inference.tool_request(
            SimpleNamespace(game_id="session"), settings, usage, messages, offered, llm=port
        )

    assert inner.calls == []
    assert usage.calls == 0 and usage.input_chars == 0


def request(name, arguments=None):
    return {"name": name, "arguments": arguments or {}}


async def selected_schema(*names):
    reply = {"requests": [request(names[0])] if names else []}
    inner = ConfiguredTextModel("json_schema", [json.dumps(reply)])
    await JsonToolPort(inner).aexecute_tool_turn(initial(), functions(*names), inner.model)
    schema = inner.calls[0][3]["response_format"]["json_schema"]["schema"]
    Draft202012Validator.check_schema(schema)
    return schema


@pytest.mark.parametrize(
    ("requests", "valid"),
    [
        ([request("approach")], True),
        ([request("approach"), request("set_pose")], True),
        ([request("submit_decision", {"choice": {"preferred": "REFUSE"}})], True),
        ([], False),
        ([request("approach"), request("set_pose"), request("submit_decision")], False),
        ([request("approach"), request("submit_decision")], False),
        ([request("submit_decision"), request("set_pose")], False),
        ([request("unknown_function")], False),
        ([{"name": "approach", "arguments": "{}"}], False),
        ([{"name": "approach", "arguments": {}, "actor_id": "invented"}], False),
    ],
)
async def test_selected_integrated_schema_enforces_batch_count_names_and_submission_isolation(
    requests, valid
):
    schema = await selected_schema("approach", "set_pose", "submit_decision")
    assert Draft202012Validator(schema).is_valid({"requests": requests}) is valid


async def test_only_submission_is_representable_after_other_functions_are_removed():
    schema = await selected_schema("submit_decision")
    validator = Draft202012Validator(schema)
    assert validator.is_valid({"requests": [request("submit_decision")]})
    assert not validator.is_valid({"requests": []})
    assert not validator.is_valid({"requests": [request("approach")]})


@pytest.mark.parametrize("names", [(), ("inspect_self", "notebook_write")])
async def test_memory_only_empty_ready_reply_keeps_its_existing_semantics(names):
    schema = await selected_schema(*names)
    validator = Draft202012Validator(schema)
    assert validator.is_valid({"requests": []})
    assert validator.is_valid({"requests": [request(name) for name in names]})
    assert not validator.is_valid({"requests": [request("unavailable")]})
    assert not validator.is_valid({"requests": [request("inspect_self")] * 3})


async def test_opaque_arguments_preserve_arbitrary_notebook_json_complete_proposals_and_metadata():
    value = {"quote": "A hypothesis, not evidence.", "自由": [None, True, 1.5], "$ref": "literal"}
    proposal = {"choice": {"preferred": "REFUSE"}, "candidates": {"REFUSE": {"motives": value}}}
    reply = {"purpose": value, "requests": [request("submit_decision", proposal)]}
    inner = ConfiguredTextModel("json_schema", [json.dumps(reply, ensure_ascii=False)])
    offered = functions("notebook_write", "submit_decision")
    turn = await JsonToolPort(inner).aexecute_tool_turn(initial(), offered, inner.model)
    schema = inner.calls[0][3]["response_format"]["json_schema"]["schema"]

    assert Draft202012Validator(schema).is_valid(reply)
    assert Draft202012Validator(schema).is_valid(
        {"requests": [request("notebook_write", {"value": value, "expected_revision": 0})]}
    )
    assert json.loads(turn.calls[0].arguments_raw) == proposal
    assert "#/parameter_schemas/" not in json.dumps(schema)
    assert "#/conversation/" not in json.dumps(schema)


async def test_metadata_remains_json_typed_when_an_untyped_decoder_node_defaults_to_object():
    schema = await selected_schema("inspect_self")
    # This decoder compatibility behavior must not narrow optional metadata to objects.
    if schema["properties"]["purpose"] == {}:
        schema["properties"]["purpose"] = {"type": "object"}
    validator = Draft202012Validator(schema)
    values = [None, False, 3, 1.5, "A private consideration.", [1, {"nested": True}], {"x": []}]
    assert [validator.is_valid({"requests": [], "purpose": value}) for value in values] == [
        True
    ] * len(values)


async def test_empty_tool_catalog_does_not_require_a_boolean_item_schema():
    schema = await selected_schema()
    constraint = schema["properties"]["requests"]
    assert isinstance(constraint.get("items", {}), dict)
    validator = Draft202012Validator(schema)
    assert validator.is_valid({"requests": []})
    assert not validator.is_valid({"requests": [request("unavailable")]})


@pytest.mark.parametrize(
    ("provider", "mode", "expected"),
    [
        ("custom_openai", "prompt", None),
        ("custom_openai", "json_object", "json_object"),
        ("custom_openai", "json_schema", "json_schema"),
        ("openai", "prompt", "json_object"),
        ("anthropic", "prompt", None),
        ("ollama", "prompt", "json_schema"),
        ("openrouter", "prompt", "json_object"),
        ("", "json_schema", None),
    ],
)
async def test_existing_provider_policy_keeps_opaque_argument_fallbacks(provider, mode, expected):
    inner = ConfiguredTextModel(mode)
    inner.provider = provider
    await JsonToolPort(inner).aexecute_tool_turn(initial(), functions("inspect_self"), inner.model)
    selected = inner.calls[0][3]["response_format"]
    assert (selected["type"] if selected else None) == expected
    assert len(inner.calls) == 1


async def test_port_without_explicit_format_keyword_retains_plain_text_and_identical_sizing():
    inner = TextModel(['{"requests":[]}'])
    inner.provider, inner.custom_response_format = "custom_openai", "json_schema"
    port = JsonToolPort(inner)
    messages, offered = initial(), functions("inspect_self")
    assert port.input_size(messages, offered) == sum(map(len, compose(messages, offered)))

    await port.aexecute_tool_turn(messages, offered, inner.model)

    assert inner.calls[0][3] == {"operation": "chpm"}


async def test_positional_only_format_parameter_does_not_claim_keyword_support():
    class PositionalFormat(TextModel):
        async def aexecute_simple_task(
            self, system, payload, model, response_format=None, /, **kwargs
        ):
            assert response_format is None
            return await super().aexecute_simple_task(system, payload, model, **kwargs)

    inner = PositionalFormat(['{"requests":[]}'])
    inner.provider, inner.custom_response_format = "custom_openai", "json_schema"
    port = JsonToolPort(inner)
    messages, offered = initial(), functions("inspect_self")
    assert port.input_size(messages, offered) == sum(map(len, compose(messages, offered)))

    await port.aexecute_tool_turn(messages, offered, inner.model)

    assert inner.calls[0][3] == {"operation": "chpm"}


@pytest.mark.parametrize("mode", ["prompt", "json_object", "json_schema"])
async def test_exact_selected_format_boundary_is_admitted_without_removing_context(mode):
    inner = ConfiguredTextModel(mode)
    port = JsonToolPort(inner)
    messages, offered = initial(), functions("inspect_self")
    host = json.loads(messages[1]["content"])
    host["padding"] = "x" * 8000
    messages[1]["content"] = json.dumps(host)
    expected_size = port.input_size(messages, offered)
    usage = Usage()

    await inference.tool_request(
        SimpleNamespace(game_id="session"),
        Settings(mode="live", actor_ids=["NPC"], agent_steps=1, max_input_chars=expected_size),
        usage,
        messages,
        offered,
        llm=port,
    )

    system, payload, _, options = inner.calls[0]
    actual_format = options["response_format"]
    format_size = (
        len(json.dumps(actual_format, ensure_ascii=False, separators=(",", ":")))
        if actual_format is not None
        else 0
    )
    assert (
        len(system)
        + len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
        + format_size
        == expected_size
    )
    assert payload["padding"] == host["padding"]
    assert usage.calls == 1 and usage.input_chars == expected_size
