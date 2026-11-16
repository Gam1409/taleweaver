"""Finite nullable discriminators retain native structure and canonical host checks."""

from copy import deepcopy

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from backend.core.llm_schema_merge import SchemaProjectionError
from backend.core.llm_schema_projection import project
from backend.core.llm_structured_output import select
from backend.engine.physical_conditions.schema import ConditionProposal
from tests.test_llm_schema_projection import transport


def conditional(discriminator, *, required=False):
    return {
        "type": "object",
        "properties": {"kind": discriminator, "detail": {"type": "string"}},
        "additionalProperties": False,
        "required": ["kind"] if required else [],
        "allOf": [
            {
                "if": {"properties": {"kind": {"const": "item_state"}}, "required": ["kind"]},
                "then": {"properties": {"detail": {"minLength": 4}}, "required": ["detail"]},
            }
        ],
    }


@pytest.mark.parametrize(
    "discriminator",
    [
        {"type": "null"},
        {"type": "string", "const": "item_state"},
        {"const": None},
        {"anyOf": [{"type": "string", "enum": ["item_state", "other"]}, {"type": "null"}]},
        {"anyOf": [{"type": "string", "enum": ["item_state", "other"]}, False]},
    ],
)
@pytest.mark.parametrize("required", [False, True])
def test_finite_nullable_discriminators_preserve_conditional_acceptance(discriminator, required):
    canonical = conditional(discriminator, required=required)
    original = deepcopy(canonical)
    projected = project(canonical).schema
    host = Draft202012Validator(canonical)
    decoder = Draft202012Validator(projected)
    for body in (
        {},
        {"detail": "x"},
        {"kind": None},
        {"kind": "other", "detail": "x"},
        {"kind": "item_state"},
        {"kind": "item_state", "detail": "x"},
        {"kind": "item_state", "detail": "valid"},
        {"kind": "unsupported", "detail": "valid"},
    ):
        assert decoder.is_valid(body) is host.is_valid(body), body
    assert canonical == original


def test_boolean_discriminator_does_not_match_an_integer_predicate():
    canonical = conditional({"const": False})
    canonical["allOf"][0]["if"]["properties"]["kind"]["const"] = 0
    projected = Draft202012Validator(project(canonical).schema)
    assert projected.is_valid({"kind": False, "detail": "x"})
    assert projected.is_valid({})


@pytest.mark.parametrize("value,expected", [(1, 1.0), (1.0, 1)])
def test_equivalent_json_numbers_match_the_conditional(value, expected):
    canonical = conditional({"const": value})
    canonical["allOf"][0]["if"]["properties"]["kind"]["const"] = expected
    projected = Draft202012Validator(project(canonical).schema)
    assert not projected.is_valid({"kind": value, "detail": "x"})
    assert projected.is_valid({"kind": value, "detail": "valid"})
    assert projected.is_valid({})


@pytest.mark.parametrize(
    "value,expected,matches",
    [
        ([False], [0], False),
        ({"flag": False}, {"flag": 0}, False),
        ({"nested": [{"flag": False}]}, {"nested": [{"flag": 0}]}, False),
        ([{"number": 1}], [{"number": 1.0}], True),
        ({"nested": [1.0, {"flag": False}]}, {"nested": [1, {"flag": False}]}, True),
        ([1], [1, 2], False),
        ({"value": 1}, {"value": 1, "other": 2}, False),
    ],
)
def test_composite_discriminators_keep_explicit_local_validation(value, expected, matches):
    canonical = conditional({"const": value})
    canonical["allOf"][0]["if"]["properties"]["kind"]["const"] = expected
    host = Draft202012Validator(canonical)
    body = {"kind": value, "detail": "x"}
    assert host.is_valid(body) is not matches
    assert host.is_valid({"kind": value, "detail": "valid"})
    assert host.is_valid({})
    with pytest.raises(SchemaProjectionError, match="local.*validation"):
        project(canonical)
    contract = select(
        "custom_openai", "", ConditionProposal, schema=canonical, custom_mode="json_schema"
    )
    assert contract.mode == "json_object"
    assert contract.local_checks == ("schema_projection",)


@pytest.mark.parametrize(
    "discriminator",
    [
        {"enum": [[False], [0]]},
        {"enum": [{"flag": False}, {"flag": 0}]},
        {"anyOf": [{"const": None}, {"const": [{"number": 1.0}]}]},
    ],
)
def test_unsafe_discriminator_intersections_use_the_reported_local_mode(discriminator):
    canonical = conditional(discriminator)
    with pytest.raises(SchemaProjectionError, match="local.*validation"):
        project(canonical)
    contract = select(
        "custom_openai", "", ConditionProposal, schema=canonical, custom_mode="json_schema"
    )
    assert contract.mode == "json_object"
    assert contract.local_checks == ("schema_projection",)


@pytest.mark.parametrize(
    "discriminator",
    [
        {"type": "integer", "const": 1.0},
        {"type": "integer", "enum": [0.0, 1.0]},
        {"type": "integer", "anyOf": [{"const": 1.0}]},
        {"anyOf": [{"type": "integer", "const": 1.0}]},
        {"anyOf": [{"type": "integer", "const": 1.0}, {"const": 2}]},
        {"type": "integer", "anyOf": [{"const": 1.0}, {"const": 2}]},
        {"type": ["integer", "null"], "enum": [1.0, 2, None]},
        {"type": ["integer", "null"], "anyOf": [{"const": 1.0}, {"const": 2}]},
        {"allOf": [{"type": "integer"}, {"const": 1.0}]},
        {"type": "integer", "allOf": [{"const": 1.0}]},
    ],
)
def test_integer_union_literals_cannot_disappear_during_projection(discriminator):
    canonical = conditional(discriminator)
    canonical["allOf"][0]["if"]["properties"]["kind"]["const"] = 1
    original = deepcopy(canonical)
    host = Draft202012Validator(canonical)
    assert host.is_valid({"kind": 1, "detail": "valid"})
    contract = select(
        "custom_openai", "", ConditionProposal, schema=canonical, custom_mode="json_schema"
    )
    assert contract.mode == "json_schema"
    decoder = Draft202012Validator(contract.response_format["json_schema"]["schema"])
    for body in (
        {},
        {"detail": "x"},
        *(
            {"kind": value, "detail": detail}
            for value in (None, False, 0, 0.0, 1, 1.0, 1.5, 2, 2.0, "1")
            for detail in ("x", "valid")
        ),
    ):
        assert decoder.is_valid(body) is host.is_valid(body), body
    assert canonical == original


@pytest.mark.parametrize("part", ["fill_level", "Invalid Property", "_invalid", "a" * 81])
def test_item_property_keys_keep_native_structure_and_strict_local_validation(part):
    body = {
        "operation": "record",
        "target_id": "FLASK",
        "kind": "item_state",
        "part": part,
        "detail": "half full",
        "evidence": "The flask is half full.",
    }
    canonical = ConditionProposal.model_json_schema()
    decoder = transport(ConditionProposal)
    assert Draft202012Validator(decoder).is_valid(body) is (len(part) <= 80)
    valid = part == "fill_level"
    assert Draft202012Validator(canonical).is_valid(body) is valid
    if valid:
        assert ConditionProposal.model_validate(body).part == part
    else:
        with pytest.raises(ValidationError):
            ConditionProposal.model_validate(body)
    assert "pattern" in project(canonical).local_checks
    assert canonical == ConditionProposal.model_json_schema()


def test_unbounded_discriminators_still_require_explicit_local_schema_validation():
    with pytest.raises(SchemaProjectionError, match="finite discriminator"):
        project(conditional({"type": "string"}))


@pytest.mark.parametrize("constraint", ["predicate", "field", "condition"])
def test_unsupported_conditional_predicates_remain_explicit_local_checks(constraint):
    canonical = conditional({"const": "item_state"})
    condition = canonical["allOf"][0]
    if constraint == "predicate":
        condition["if"]["maxProperties"] = 0
    elif constraint == "field":
        condition["if"]["properties"]["kind"]["minLength"] = 100
    else:
        condition["maxProperties"] = 0
    with pytest.raises(SchemaProjectionError, match="local schema validation"):
        project(canonical)
