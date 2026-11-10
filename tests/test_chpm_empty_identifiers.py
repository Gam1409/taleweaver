"""Unavailable references forbid operations without breaking a server grammar."""

from copy import deepcopy

import pytest
from jsonschema import Draft202012Validator
from pydantic import BaseModel, Field

from backend.engine.chpm.json_contract import response_schema
from backend.engine.chpm.proposal_draft import Draft
from tests.test_chpm_appraisal import proposal
from tests.test_chpm_kernel import wire_proposal


def empty_enums(value):
    if isinstance(value, list):
        return any(empty_enums(child) for child in value)
    if not isinstance(value, dict):
        return False
    return value.get("enum") == [] or any(empty_enums(child) for child in value.values())


@pytest.mark.parametrize("explicit_keys", [False, True])
def test_first_npc_turn_has_no_revision_grammar_or_invented_reference(explicit_keys):
    schema = response_schema(Draft, {"belief_id": []}, explicit_keys=explicit_keys)
    assert not empty_enums(schema)
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    body = Draft.model_validate(wire_proposal()).model_dump(mode="json")
    assert validator.is_valid(body)
    invented = deepcopy(body)
    invented["belief_revisions"] = [proposal(belief_id="invented").model_dump(mode="json")]
    assert not validator.is_valid(invented)
    assert schema["properties"]["belief_revisions"]["maxItems"] == 0


def test_known_revision_ids_remain_available_and_bounded_after_an_empty_turn():
    empty = response_schema(Draft, {"belief_id": []})
    known = response_schema(Draft, {"belief_id": ["b1"]})
    assert not empty_enums(empty)
    body = Draft.model_validate(wire_proposal()).model_dump(mode="json")
    body["belief_revisions"] = [proposal(belief_id="b1").model_dump(mode="json")]
    validator = Draft202012Validator(known)
    assert validator.is_valid(body)
    body["belief_revisions"][0]["belief_id"] = "invented"
    assert not validator.is_valid(body)


def test_no_citation_sources_forbids_beliefs_and_experiences_but_allows_a_decision():
    schema = response_schema(Draft, {"source_id": [], "personal_motive_ids": []})
    assert not empty_enums(schema)
    validator = Draft202012Validator(schema)
    body = Draft.model_validate(wire_proposal()).model_dump(mode="json")
    assert validator.is_valid(body)
    body["new_beliefs"] = [
        {k: v for k, v in proposal().model_dump(mode="json").items() if k != "belief_id"}
    ]
    assert not validator.is_valid(body)
    assert schema["properties"]["experiences"]["maxItems"] == 0


def test_unavailable_nullable_reference_can_only_be_null():
    class OptionalReference(BaseModel):
        belief_id: str | None = None

    schema = response_schema(OptionalReference, {"belief_id": []})
    validator = Draft202012Validator(schema)
    assert not empty_enums(schema)
    assert validator.is_valid({}) and validator.is_valid({"belief_id": None})
    assert not validator.is_valid({"belief_id": "invented"})


def test_impossible_required_reference_stops_before_generation():
    class RequiredReference(BaseModel):
        belief_id: str

    with pytest.raises(ValueError, match="no valid|impossible|unavailable"):
        response_schema(RequiredReference, {"belief_id": []})


def test_empty_observer_map_stays_empty_instead_of_accepting_unknown_keys():
    class ObserverMap(BaseModel):
        observers: dict[str, str] = Field(default_factory=dict)

    schema = response_schema(ObserverMap, {"observers": []}, explicit_keys=True)
    validator = Draft202012Validator(schema)
    assert not empty_enums(schema)
    assert validator.is_valid({"observers": {}})
    assert not validator.is_valid({"observers": {"unknown": "a fact"}})
