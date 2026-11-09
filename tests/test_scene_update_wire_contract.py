"""The model-facing scene operations enforce the same fields as the host."""

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from backend.engine.scene_continuity.schema import Update


def test_record_wire_schema_does_not_advertise_a_payload_the_host_rejects():
    proposal = {
        "operation": "record",
        "kind": "process",
        "subject_id": "KETTLE",
        "detail": "The kettle is heating.",
        "evidence": "The kettle starts heating.",
    }
    with pytest.raises(ValidationError):
        Update.model_validate(proposal)
    assert not Draft202012Validator(Update.model_json_schema()).is_valid(proposal)


@pytest.mark.parametrize(
    "operation,patch,valid",
    [
        ("record", {}, True),
        ("record", {"key": ""}, False),
        ("record", {"key": "   "}, False),
        ("record", {"subject_id": ""}, False),
        ("record", {"detail": ""}, False),
        ("record", {"record_id": "existing"}, False),
        ("record", {"key": "x" * 80}, True),
        ("record", {"key": "x" * 81}, False),
        ("record", {"evidence": "    "}, False),
        ("record", {"source": "scene_description"}, False),
        ("record", {"source": "scene_description", "kind": "environment"}, True),
        ("change", {}, True),
        ("change", {"record_id": ""}, False),
        ("change", {"record_id": "  "}, False),
        ("change", {"key": "new"}, False),
        ("change", {"subject_id": "other"}, False),
        ("change", {"detail": ""}, False),
        ("end", {}, True),
        ("end", {"record_id": ""}, False),
        ("end", {"key": "new"}, False),
        ("end", {"detail": ""}, True),
    ],
)
def test_scene_operation_wire_requirements_match_host(operation, patch, valid):
    payload = {
        "operation": operation,
        "detail": "The kettle is heating.",
        "evidence": "The kettle starts heating.",
        **(
            {"key": "kettle-heating", "subject_id": "KETTLE"}
            if operation == "record"
            else {"record_id": "existing"}
        ),
        **patch,
    }
    assert Draft202012Validator(Update.model_json_schema()).is_valid(payload) is valid
    if valid:
        value = Update.model_validate(payload)
        assert Update.model_validate_json(value.model_dump_json()) == value
        return
    with pytest.raises(ValidationError):
        Update.model_validate(payload)


def test_shared_extractor_advertises_the_same_record_requirements():
    from backend.engine.narrated_items.schema import SharedItemExtraction

    schema = Draft202012Validator(SharedItemExtraction.model_json_schema())
    proposal = {
        "operation": "record",
        "subject_id": "KETTLE",
        "detail": "The kettle is heating.",
        "evidence": "The kettle starts heating.",
    }
    assert not schema.is_valid({"scene_updates": [proposal]})
    assert schema.is_valid({"scene_updates": [{**proposal, "key": "heating"}]})
