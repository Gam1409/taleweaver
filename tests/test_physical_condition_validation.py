"""Advertised operation rules and owner diagnostics match deferred host validation."""

import json
from copy import deepcopy

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError
from pydantic_core import PydanticCustomError

from backend.engine.narrated_items.schema import ItemExtraction
from backend.engine.physical_conditions.ledger import read
from backend.engine.physical_conditions.schema import KEY, ConditionProposal
from backend.engine.physical_conditions.validation import rejection
from tests.test_physical_conditions import record, run


@pytest.mark.parametrize("field", ["target_id", "kind", "part", "detail"])
def test_wire_requires_each_new_condition_identity_field(field):
    proposal = record()
    del proposal[field]
    wire = Draft202012Validator(ItemExtraction.model_json_schema())
    assert not wire.is_valid({"condition_updates": [proposal]})
    with pytest.raises(ValidationError):
        ConditionProposal.model_validate(proposal)
    assert ItemExtraction.model_validate({"condition_updates": [proposal]}).condition_updates


@pytest.mark.parametrize(
    "changes,valid",
    [
        ({}, True),
        ({"condition_id": None}, True),
        ({"condition_id": ""}, True),
        ({"condition_id": "  "}, True),
        ({"condition_id": "condition_existing"}, False),
        ({"target_id": ""}, False),
        ({"kind": None}, False),
        ({"part": ""}, False),
        ({"detail": ""}, False),
        ({"part": "  "}, False),
        ({"detail": "  "}, False),
        ({"target_id": "  "}, False),
        ({"target_id": "x" * 100}, True),
        ({"target_id": "x" * 101}, False),
        ({"evidence": " abc "}, False),
        ({"evidence": " abcd "}, True),
        ({"part": "x" * 80, "detail": "x" * 320, "evidence": "x" * 600}, True),
        ({"part": "x" * 81}, False),
        ({"detail": "x" * 321}, False),
        ({"evidence": "x" * 601}, False),
    ],
)
def test_record_wire_and_host_agree_at_identity_and_text_limits(changes, valid):
    proposal = record(**changes)
    assert Draft202012Validator(ConditionProposal.model_json_schema()).is_valid(proposal) is valid
    if valid:
        assert ConditionProposal.model_validate(proposal).operation == "record"
        return
    with pytest.raises(ValidationError):
        ConditionProposal.model_validate(proposal)


@pytest.mark.parametrize("operation", ["change", "treat", "reduce", "clean", "heal", "remove"])
@pytest.mark.parametrize("extra_target", [False, True])
def test_existing_condition_wire_references_only_the_condition_id(operation, extra_target):
    proposal = {
        "operation": operation,
        "condition_id": "condition_existing",
        "detail": "A changed physical fact.",
        "evidence": "The physical condition has changed.",
    }
    if extra_target:
        proposal["target_id"] = "RIN"
    assert Draft202012Validator(ConditionProposal.model_json_schema()).is_valid(proposal) is (
        not extra_target
    )
    if extra_target:
        with pytest.raises(ValidationError):
            ConditionProposal.model_validate(proposal)
        return
    assert ConditionProposal.model_validate(proposal).condition_id == "condition_existing"


def test_wire_requires_an_existing_id_and_detail_for_description_changes():
    wire = Draft202012Validator(ConditionProposal.model_json_schema())
    missing_detail = {"operation": "change", "condition_id": "known", "evidence": "Changed."}
    missing_id = {"operation": "treat", "evidence": "Treated."}
    for proposal in (missing_detail, missing_id):
        assert not wire.is_valid(proposal)
        with pytest.raises(ValidationError):
            ConditionProposal.model_validate(proposal)


@pytest.mark.parametrize(
    "changes,valid",
    [
        ({"condition_id": " "}, False),
        ({"condition_id": "x" * 100}, True),
        ({"condition_id": "x" * 101}, False),
        ({"detail": " "}, False),
        ({"target_id": " ", "kind": None, "part": " "}, True),
        ({"kind": "injury"}, False),
        ({"part": "neck"}, False),
    ],
)
def test_update_wire_and_host_agree_on_normalized_blank_fields_and_id_limits(changes, valid):
    proposal = {
        "operation": "change",
        "condition_id": "known",
        "detail": "Changed.",
        "evidence": "Changed.",
        **changes,
    }
    assert Draft202012Validator(ConditionProposal.model_json_schema()).is_valid(proposal) is valid
    if valid:
        assert ConditionProposal.model_validate(proposal).operation == "change"
        return
    with pytest.raises(ValidationError):
        ConditionProposal.model_validate(proposal)


def test_rejected_length_names_its_field_and_limit_without_erasing_accepted_conditions():
    original, identifiers, _ = run({}, [record()], reply="original")
    before = deepcopy(original)
    updated, accepted, errors = run(
        original,
        [record(detail="PRIVATE_TEXT" * 40), record(part="arm")],
        reply="later",
    )
    assert len(errors) == 1 and "detail" in errors[0] and "320" in errors[0]
    assert "PRIVATE_TEXT" not in errors[0]
    assert len(accepted) == 1 and len(read(updated).conditions) == 2
    assert read(updated).conditions[identifiers[0]] == read(before).conditions[identifiers[0]]
    assert original == before
    restored = read(json.loads(json.dumps(updated)))
    assert restored.version == 1 and restored.last_check["rejected"] == errors


def test_rejected_operation_combination_explains_the_existing_id_rule():
    _, accepted, errors = run(
        {}, [{"operation": "clean", "target_id": "RIN", "evidence": "Rin washed her hands."}]
    )
    assert not accepted
    assert "existing condition ID" in errors[0]


def test_unknown_field_and_value_never_appear_in_validation_feedback():
    _, accepted, errors = run(
        {}, [record(operation="PRIVATE_OPERATION", PRIVATE_FIELD="PRIVATE_INPUT")]
    )
    assert not accepted and "operation" in errors[0]
    assert not any(
        secret in errors[0] for secret in ("PRIVATE_OPERATION", "PRIVATE_FIELD", "PRIVATE_INPUT")
    )


def test_legacy_generic_diagnostic_loads_without_rewriting_facts():
    states, identifiers, _ = run({}, [record()])
    states[KEY]["last_check"]["rejected"] = ["Condition proposal 1: invalid fields."]
    restored = read(json.loads(json.dumps(states)))
    assert restored.conditions[identifiers[0]].detail == record()["detail"]
    assert restored.last_check["rejected"] == ["Condition proposal 1: invalid fields."]


def test_unknown_validator_reason_is_not_reflected_and_diagnostics_are_bounded():
    error = ValidationError.from_exception_data(
        "ConditionProposal",
        [
            {
                "type": PydanticCustomError("PRIVATE_CODE", "PRIVATE_REASON"),
                "loc": ("PRIVATE_FIELD",),
                "input": "PRIVATE_INPUT",
            }
            for _ in range(20)
        ],
    )
    text = rejection(0, error)
    assert len(text.split("; ")) == 5 and len(text) < 1000
    assert "PRIVATE" not in text and "physical condition schema" in text
