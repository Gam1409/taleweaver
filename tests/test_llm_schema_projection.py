"""Decoder schemas retain operation identities while host predicates stay strict."""

from copy import deepcopy
from types import SimpleNamespace

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from backend.core.custom_openai import structured_response_format
from backend.core.llm_schema_projection import project
from backend.engine.narrated_items.schema import SharedItemExtraction
from backend.engine.physical_conditions.schema import ConditionProposal
from backend.engine.scene_continuity.schema import Update


def transport(model):
    result = structured_response_format(
        SimpleNamespace(custom_response_format="json_schema"), model
    )
    return result["json_schema"]["schema"]


def nodes(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from nodes(child)
    elif isinstance(value, list):
        for child in value:
            yield from nodes(child)


@pytest.mark.parametrize("model", [ConditionProposal, Update, SharedItemExtraction])
def test_decoder_has_no_unsupported_patterns_or_mixed_operation_branches(model):
    original = deepcopy(model.model_json_schema())
    schema = transport(model)
    Draft202012Validator.check_schema(schema)
    assert all("pattern" not in node for node in nodes(schema))
    assert all(
        not ("properties" in node and ("oneOf" in node or "anyOf" in node))
        for node in nodes(schema)
    )
    assert all("if" not in node for node in nodes(schema))
    assert original == model.model_json_schema()


@pytest.mark.parametrize(
    "patch,valid",
    [
        ({}, True),
        ({"condition_id": "existing"}, False),
        ({"target_id": None}, False),
        ({"target_id": "x" * 101}, False),
        ({"kind": None}, False),
        ({"kind": "invented"}, False),
        ({"detail": ""}, False),
        ({"detail": "x" * 321}, False),
        ({"evidence": "x" * 601}, False),
    ],
)
def test_record_operation_keeps_identity_types_enums_and_bounds(patch, valid):
    body = {
        "operation": "record",
        "target_id": "COAT",
        "kind": "contamination",
        "part": "sleeve",
        "detail": "Ink stain",
        "evidence": "Ink marks the sleeve.",
        **patch,
    }
    assert Draft202012Validator(transport(ConditionProposal)).is_valid(body) is valid


@pytest.mark.parametrize("operation", ["change", "treat", "reduce", "clean", "heal", "remove"])
def test_existing_condition_cannot_acquire_a_new_target_or_body_part(operation):
    body = {
        "operation": operation,
        "condition_id": "known",
        "detail": "Changed.",
        "evidence": "The condition changes.",
    }
    validator = Draft202012Validator(transport(ConditionProposal))
    assert validator.is_valid(body)
    for patch in (
        {"target_id": "COAT"},
        {"kind": "injury"},
        {"part": "neck"},
        {"condition_id": None},
    ):
        assert not validator.is_valid({**body, **patch})


@pytest.mark.parametrize("operation", ["record", "change", "end"])
def test_authored_scene_description_can_only_establish_environment(operation):
    body = {
        "operation": operation,
        "source": "scene_description",
        "kind": "environment",
        "detail": "Warm brass lighting.",
        "evidence": "Warm brass lamps light the room.",
        **(
            {"key": "lighting", "subject_id": "room"}
            if operation == "record"
            else {"record_id": "known"}
        ),
    }
    validator = Draft202012Validator(transport(Update))
    assert validator.is_valid(body)
    assert not validator.is_valid({**body, "kind": "process"})
    assert not validator.is_valid({**body, "kind": "effect"})


def test_text_predicates_are_still_checked_by_the_canonical_host_model():
    body = {
        "operation": "record",
        "target_id": "COAT",
        "kind": "contamination",
        "part": "sleeve",
        "detail": "Ink stain",
        "evidence": "    ",
    }
    assert Draft202012Validator(transport(ConditionProposal)).is_valid(body)
    with pytest.raises(ValidationError):
        ConditionProposal.model_validate(body)


def test_fixed_homogeneous_tuple_keeps_both_positions_without_prefix_items():
    from pydantic import BaseModel

    class Pair(BaseModel):
        evidence: tuple[str, str]

    schema = project(Pair.model_json_schema()).schema
    assert all("prefixItems" not in node for node in nodes(schema))
    validator = Draft202012Validator(schema)
    assert validator.is_valid({"evidence": ["first", "second"]})
    assert not validator.is_valid({"evidence": ["first"]})
    assert not validator.is_valid({"evidence": ["first", "second", "third"]})
