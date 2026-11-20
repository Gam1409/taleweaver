"""Portable schemas keep resolvable references after embedding and fragment factoring."""

import json
from copy import deepcopy

import pytest
from jsonschema import Draft202012Validator

from backend.engine.chpm.json_tool_port import compose
from backend.engine.chpm.proposal_draft import Draft


def tool(name, schema):
    return {"type": "function", "function": {"name": name, "parameters": schema}}


def payload(*tools):
    _, serialized = compose(
        [{"role": "system", "content": "A neutral task."}, {"role": "user", "content": "{}"}],
        list(tools),
    )
    return json.loads(serialized)


def target(body, reference):
    value = body
    for raw in reference.removeprefix("#/").split("/"):
        part = raw.replace("~1", "/").replace("~0", "~")
        value = value[int(part)] if isinstance(value, list) else value[part]
    return value


def resolved(body, node, seen=()):
    if isinstance(node, list):
        return [resolved(body, value, seen) for value in node]
    if not isinstance(node, dict):
        return node
    if set(node) == {"$ref"}:
        reference = node["$ref"]
        assert reference not in seen, "This helper expands only nonrecursive schemas."
        return resolved(body, target(body, reference), (*seen, reference))
    return {key: resolved(body, value, seen) for key, value in node.items()}


def assert_references_exist(body):
    pending = [body]
    while pending:
        node = pending.pop()
        if isinstance(node, dict):
            if "$ref" in node:
                assert isinstance(target(body, node["$ref"]), dict)
            pending.extend(node.values())
        elif isinstance(node, list):
            pending.extend(node)


def test_actual_submit_decision_schema_resolves_from_the_portable_payload_root():
    body = payload(tool("submit_decision", Draft.model_json_schema()))
    assert_references_exist(body)
    schema = resolved(body, body["functions"][0]["parameters"])
    assert schema["properties"]["choice"]["type"] == "object"
    assert schema["properties"]["candidates"]["type"] == "object"
    assert {"intention", "message_plan"} & schema["properties"]["candidates"][
        "additionalProperties"
    ]["properties"].keys()


def test_same_local_definition_name_in_two_functions_does_not_merge_different_constraints():
    original = {
        "$defs": {"Value": {"type": "string", "enum": ["left"]}},
        "type": "object",
        "properties": {"value": {"$ref": "#/$defs/Value"}},
        "required": ["value"],
        "additionalProperties": False,
    }
    other = deepcopy(original)
    other["$defs"]["Value"]["enum"] = ["right"]
    before = deepcopy(original), deepcopy(other)
    body = payload(tool("left", original), tool("right", other))
    assert_references_exist(body)
    left = resolved(body, body["functions"][0]["parameters"])
    right = resolved(body, body["functions"][1]["parameters"])
    Draft202012Validator(left).validate({"value": "left"})
    Draft202012Validator(right).validate({"value": "right"})
    assert not Draft202012Validator(left).is_valid({"value": "right"})
    assert (original, other) == before


def test_escaped_local_definition_names_remain_resolvable_and_reused():
    schema = {
        "$defs": {"A/B~C": {"type": "string", "minLength": 3}},
        "type": "object",
        "properties": {"one": {"$ref": "#/$defs/A~1B~0C"}, "two": {"$ref": "#/$defs/A~1B~0C"}},
    }
    body = payload(tool("escaped", schema))
    assert_references_exist(body)
    expanded = resolved(body, body["functions"][0]["parameters"])
    assert expanded["properties"]["one"] == expanded["properties"]["two"]
    assert expanded["properties"]["one"]["minLength"] == 3


def test_recursive_local_refs_are_relocated_without_expanding_the_recursion():
    schema = {
        "$defs": {
            "Node": {
                "type": "object",
                "properties": {"next": {"anyOf": [{"$ref": "#/$defs/Node"}, {"type": "null"}]}},
            }
        },
        "$ref": "#/$defs/Node",
    }
    body = payload(tool("recursive", schema))
    assert_references_exist(body)
    assert len(json.dumps(body)) < 2000


@pytest.mark.parametrize("reference", ["#/properties/base", "#/$defs/Value"])
def test_local_refs_and_shared_fragment_factoring_can_coexist(reference):
    repeated = {
        "type": "string",
        "minLength": 2,
        "maxLength": 32,
        "description": "A repeated field description long enough to factor.",
    }
    schema = {
        "$defs": {"Value": repeated},
        "type": "object",
        "properties": {
            "base": repeated,
            **{f"copy_{index}": {"$ref": reference} for index in range(8)},
        },
    }
    body = payload(tool("factor", schema))
    assert_references_exist(body)
    expanded = resolved(body, body["functions"][0]["parameters"])
    assert expanded["properties"]["copy_0"]["maxLength"] == 32
