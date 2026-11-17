"""Unrestricted JSON stays unrestricted on decoders that default untyped nodes to objects."""

from copy import deepcopy
from types import SimpleNamespace

import pytest
from jsonschema import Draft202012Validator

from backend.core.llm_schema_compaction import map_schema
from backend.core.llm_schema_projection import project
from backend.core.llm_schema_values import json_equal
from backend.core.llm_structured_output import for_router
from backend.engine.chpm import json_contract
from backend.engine.chpm.proposal_edits import Corrections

VALUES = (
    None,
    False,
    True,
    0,
    1.5,
    "A supported correction.",
    '{"literal": {"type": "object", "$ref": "data, not schema"}}',
    [],
    [None, "Проверить 明日", {"nested": [1, True]}],
    {},
    {"自由": [None, False, 1.5], "$ref": "literal", "title": {"properties": {}}},
)
PATHS = ["/choice/reason", "/experiences", "/question_gate"]


def object_default_decoder(schema):
    """Model the known decoder behavior only at schema positions, never literal JSON data."""
    return map_schema(schema, lambda node: node if node else {"type": "object"})


def selected(model=Corrections, *, provider="custom_openai", schema=None, mode="json_schema"):
    return for_router(
        SimpleNamespace(provider=provider, model="offline-model", custom_response_format=mode),
        model,
        schema=schema,
    )


def correction(value):
    return {"edits": [{"op": "replace", "path": PATHS[0], "value": value}]}


def test_native_correction_wire_supports_every_locally_valid_json_value():
    raw = json_contract.response_schema(Corrections, {"path": PATHS})
    original = deepcopy(raw)
    output = selected(schema=raw)
    assert output.mode == "json_schema"
    wire = output.response_format["json_schema"]["schema"]
    Draft202012Validator.check_schema(wire)
    validator = Draft202012Validator(object_default_decoder(wire))

    for value in VALUES:
        sample = correction(value)
        assert validator.is_valid(sample), type(value).__name__
        local = Corrections.model_validate(sample)
        assert json_equal(local.edits[0].value, value)
    assert raw == original


@pytest.mark.parametrize(
    "raw",
    [
        {},
        {"title": "Any value", "description": "No type restriction."},
        {"default": {"literal": {}}, "examples": [None, {"type": "object"}]},
        {"allOf": [{}]},
    ],
)
def test_empty_or_annotation_only_schema_remains_any_json_after_decoder_conversion(raw):
    original = deepcopy(raw)
    projected = project(raw)
    validator = Draft202012Validator(object_default_decoder(projected.schema))

    assert all(validator.is_valid(value) for value in VALUES)
    assert projected.local_checks == ()
    assert raw == original


def test_a_deferred_untyped_text_predicate_retains_all_json_types_in_the_decoder():
    raw = {"pattern": "^[A-Z]+$"}
    original = deepcopy(raw)
    projected = project(raw)
    validator = Draft202012Validator(object_default_decoder(projected.schema))

    assert all(validator.is_valid(value) for value in VALUES)
    assert projected.local_checks == ("pattern",)
    assert raw == original


@pytest.mark.parametrize(
    "value_schema", [{}, True, {"description": "A value without a type constraint."}]
)
def test_unrestricted_properties_items_and_dictionary_values_keep_all_json_kinds(value_schema):
    raw = {
        "type": "object",
        "properties": {
            "value": value_schema,
            "array": {"type": "array", "items": value_schema},
            "mapping": {"type": "object", "additionalProperties": value_schema},
        },
        "required": ["value", "array", "mapping"],
        "additionalProperties": False,
    }
    original = deepcopy(raw)
    validator = Draft202012Validator(object_default_decoder(project(raw).schema))

    for value in VALUES:
        assert validator.is_valid({"value": value, "array": [value], "mapping": {"a/~": value}})
    assert raw == original


def test_literal_empty_json_and_schema_looking_values_are_not_projected_as_schema_nodes():
    literal = {"title": "Literal", "$ref": "not a reference", "properties": {"x": {}}}
    raw = {
        "type": "object",
        "properties": {
            "empty": {"const": {}},
            "choice": {"enum": [{}, literal]},
            "fixed": {"const": literal},
        },
        "required": ["empty", "choice", "fixed"],
        "additionalProperties": False,
    }
    original = deepcopy(raw)
    result = project(raw).schema
    assert result["properties"]["empty"]["const"] == {}
    assert result["properties"]["choice"]["enum"] == [{}, literal]
    assert result["properties"]["fixed"]["const"] == literal
    validator = Draft202012Validator(object_default_decoder(result))

    assert validator.is_valid({"empty": {}, "choice": literal, "fixed": literal})
    assert validator.is_valid({"empty": {}, "choice": {}, "fixed": literal})
    assert not validator.is_valid({"empty": None, "choice": {}, "fixed": literal})
    assert raw == original


@pytest.mark.parametrize(
    "schema",
    [{"type": "object"}, {"type": "object", "properties": {}, "additionalProperties": False}],
)
def test_a_typed_object_never_becomes_an_unrestricted_value(schema):
    result = project(schema).schema
    validator = Draft202012Validator(object_default_decoder(result))
    assert validator.is_valid({})
    assert all(not validator.is_valid(value) for value in (None, False, 0, 1.5, "", []))


def test_empty_allof_branch_does_not_weaken_an_existing_numeric_constraint():
    raw = {"allOf": [{}, {"type": "integer", "minimum": 1, "maximum": 3}]}
    projected = project(raw).schema
    before, after = Draft202012Validator(raw), Draft202012Validator(projected)
    assert all(
        before.is_valid(value) == after.is_valid(value)
        for value in (None, False, True, 0, 1, 1.5, 2, 2.0, 3, 4, [], {})
    )


@pytest.mark.parametrize("reference_first", [False, True])
def test_neutral_empty_intersection_keeps_an_existing_native_reference(reference_first):
    branches = [{"$ref": "#/$defs/Leaf"}, {}]
    raw = {
        "type": "object",
        "properties": {"value": {"allOf": branches if reference_first else branches[::-1]}},
        "required": ["value"],
        "additionalProperties": False,
        "$defs": {"Leaf": {"type": "string", "maxLength": 30}},
    }
    original = deepcopy(raw)
    output = selected(schema=raw)

    assert output.mode == "json_schema"
    assert output.local_checks == ()
    wire = output.response_format["json_schema"]["schema"]
    before, after = Draft202012Validator(raw), Draft202012Validator(wire)
    for value in (*VALUES, "x" * 31):
        assert before.is_valid({"value": value}) == after.is_valid({"value": value})
    assert raw == original


@pytest.mark.parametrize(
    "provider,mode,expected",
    [
        ("custom_openai", "json_schema", "json_schema"),
        ("custom_openai", "json_object", "json_object"),
        ("custom_openai", "prompt", "prompt"),
        ("ollama", "prompt", "json_schema"),
        ("openai", "prompt", "json_object"),
        ("anthropic", "prompt", "prompt"),
    ],
)
def test_unrestricted_json_uses_existing_provider_fallbacks_without_closing_values(
    provider, mode, expected
):
    output = selected(provider=provider, mode=mode)
    assert output.mode == expected
    if provider in {"openai", "anthropic"}:
        assert output.local_checks == ("schema_projection",)
    if expected == "json_schema":
        schema = output.response_format["json_schema"]["schema"]
        validator = Draft202012Validator(object_default_decoder(schema))
        assert all(validator.is_valid(correction(value)) for value in VALUES)
