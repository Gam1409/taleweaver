"""Portable decoder arguments reuse canonical tool declarations and host validation."""

import json
from copy import deepcopy

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from backend.engine.chpm import json_contract, json_tool_output
from backend.engine.chpm.native_tool_contracts import parse_call, tool_definitions
from backend.engine.chpm.proposal_draft import Draft
from backend.engine.npc_actions.tool_schema import definitions as action_definitions
from tests.test_chpm_json_output_policy import ConfiguredTextModel
from tests.test_chpm_kernel import wire_proposal


def function(name, parameters):
    return {"type": "function", "function": {"name": name, "parameters": parameters}}


def offered():
    return [
        *tool_definitions(),
        *action_definitions({"approach", "set_pose"}),
        function("submit_decision", json_contract.response_schema(Draft, None, explicit_keys=True)),
    ]


def selected(tools):
    value = json_tool_output.selected(ConfiguredTextModel("json_schema"), tools)
    assert value["type"] == "json_schema"
    schema = value["json_schema"]["schema"]
    Draft202012Validator.check_schema(schema)
    return schema


def envelope(name, arguments):
    return {"requests": [{"name": name, "arguments": arguments}]}


def proposal():
    return Draft.model_validate(wire_proposal()).model_dump(mode="json", by_alias=True)


@pytest.mark.parametrize("defect", ["candidate_key", "missing_roots"])
def test_real_submission_contract_rejects_the_observed_nested_format_errors(defect):
    valid = proposal()
    Draft.model_validate(valid)
    invalid = deepcopy(valid)
    if defect == "candidate_key":
        invalid["candidates"]["question_gate"] = None
    else:
        invalid = {"choice": deepcopy(valid["choice"]), "continuity": "new", "change_basis": []}
        invalid["choice"].pop("continuity")
    with pytest.raises(ValidationError):
        Draft.model_validate(invalid)

    validator = Draft202012Validator(selected(offered()))
    assert validator.is_valid(envelope("submit_decision", valid))
    assert not validator.is_valid(envelope("submit_decision", invalid))


@pytest.mark.parametrize(
    ("name", "arguments", "accepted"),
    [
        ("approach", {"target_id": "@player", "mode": "crawl"}, True),
        ("set_pose", {"posture": "on_all_fours"}, True),
        ("approach", {"posture": "on_all_fours"}, False),
        ("set_pose", {"target_id": "@player", "mode": "crawl"}, False),
        ("inspect_self", {}, True),
        ("inspect_self", {"argument": ""}, False),
        ("not_offered", {}, False),
    ],
)
def test_function_names_select_their_own_argument_contract(name, arguments, accepted):
    validator = Draft202012Validator(selected(offered()))
    assert validator.is_valid(envelope(name, arguments)) is accepted
    if accepted:
        parse_call(name, json.dumps(arguments))


def test_two_actions_and_standalone_submission_keep_the_existing_batch_contract():
    validator = Draft202012Validator(selected(offered()))
    first = envelope("approach", {"target_id": "@player", "mode": "crawl"})["requests"][0]
    second = envelope("set_pose", {"posture": "on_all_fours"})["requests"][0]
    final = envelope("submit_decision", proposal())["requests"][0]
    assert validator.is_valid({"requests": [first, second]})
    assert validator.is_valid({"requests": [final]})
    assert not validator.is_valid({"requests": [first, final]})
    assert not validator.is_valid({"requests": [first, second, final]})
    assert not validator.is_valid({"requests": []})


def test_each_tool_keeps_its_local_definition_scope_and_escaped_definition_names():
    def parameters(value):
        return {
            "$defs": {"A/B~C": {"type": "string", "enum": [value]}},
            "type": "object",
            "additionalProperties": False,
            "properties": {"value": {"$ref": "#/$defs/A~1B~0C"}},
            "required": ["value"],
        }

    tools = [function("left", parameters("one")), function("right", parameters("two"))]
    before = deepcopy(tools)
    validator = Draft202012Validator(selected(tools))
    assert validator.is_valid(envelope("left", {"value": "one"}))
    assert validator.is_valid(envelope("right", {"value": "two"}))
    assert not validator.is_valid(envelope("left", {"value": "two"}))
    assert not validator.is_valid(envelope("right", {"value": "one"}))
    assert tools == before


def test_literal_json_schema_words_and_arbitrary_notebook_values_are_not_reinterpreted():
    literal = {"title": "KEEP", "default": {"description": "DATA"}, "$ref": "literal://data"}
    parameters = {
        "type": "object",
        "additionalProperties": False,
        "properties": {"value": {"const": literal}},
        "required": ["value"],
    }
    tools = [*tool_definitions(), function("literal", parameters)]
    before = deepcopy(tools)
    validator = Draft202012Validator(selected(tools))
    assert validator.is_valid(envelope("literal", {"value": literal}))
    assert not validator.is_valid(envelope("literal", {"value": {}}))
    for value in (None, False, 12, 1.5, "null", '{"x":1}', [literal], {"自由": [literal]}):
        arguments = {"path": "", "expected_revision": 0, "value": value}
        assert validator.is_valid(envelope("notebook_write", arguments))
        parsed = parse_call("notebook_write", json.dumps(arguments, ensure_ascii=False))
        assert json.loads(parsed.value_json) == value
    assert tools == before


@pytest.mark.parametrize(
    "parameters",
    [
        {"$ref": "https://invalid.example/schema"},
        {"$ref": "#/$defs/missing"},
        {"$id": "https://invalid.example/base", "type": "object"},
        {"$defs": {"Node": {"$ref": "#/$defs/Node"}}, "$ref": "#/$defs/Node"},
    ],
)
def test_unsafe_reference_graphs_keep_the_existing_outer_policy_without_fetching(
    caplog, parameters
):
    tools = [function("read", parameters)]
    before = deepcopy(tools)
    with caplog.at_level("WARNING", logger="backend.engine.chpm.json_tool_output"):
        value = selected(tools)
    assert Draft202012Validator(value).is_valid(envelope("read", {}))
    assert "arguments=envelope" in caplog.text
    assert tools == before


@pytest.mark.parametrize("mode", ["prompt", "json_object"])
def test_weaker_configured_modes_do_not_build_or_change_argument_contracts(mode):
    tools = [function("read", {"$ref": "https://invalid.example/schema"})]
    selected_format = json_tool_output.selected(ConfiguredTextModel(mode), tools)
    assert selected_format == (None if mode == "prompt" else {"type": "json_object"})
