"""Distinct wire arrays avoid ambiguous new-versus-revision unions."""

import pytest
from pydantic import ValidationError

from backend.engine.chpm import appraisal, appraisal_context, motivation
from backend.engine.chpm.json_contract import response_schema
from backend.engine.chpm.kernel import ChpmError
from backend.engine.chpm.proposal_draft import Draft
from tests.test_chpm_appraisal import accept, heard, proposal
from tests.test_chpm_kernel import wire_proposal


def new_belief(**changes):
    return proposal(**changes).model_dump(exclude={"belief_id"})


def test_new_and_revision_arrays_materialize_into_existing_canonical_protocol():
    value = accept(heard(), [proposal()])
    window = appraisal_context.build(value)
    raw = wire_proposal()
    raw["new_beliefs"] = [new_belief(domain="competence", statement="Ability remains unclear")]
    raw["belief_revisions"] = [proposal(belief_id="b1", stance="challenge").model_dump()]
    result = Draft.model_validate(raw).materialize(motivation.build(value, [], window))
    assert len(result.interpretations) == 2
    changed, _ = appraisal.accept(value, result.interpretations, window, message_id="next")
    assert len(changed.snapshot.beliefs) == 2
    assert changed.snapshot.beliefs[0].status == "challenged"
    assert changed.genesis == value.genesis
    assert "new_beliefs" not in result.model_dump()


@pytest.mark.parametrize(
    "failure", ["new_id", "revision_statement", "revision_subject", "three", "old_union", "missing"]
)
def test_mixed_revision_fields_and_total_overflow_are_rejected(failure):
    raw = wire_proposal()
    if failure == "new_id":
        raw["new_beliefs"] = [{**new_belief(), "belief_id": "b1"}]
    elif failure.startswith("revision_"):
        field = "statement" if failure == "revision_statement" else "about_id"
        raw["belief_revisions"] = [{**proposal(belief_id="b1").model_dump(), field: "replacement"}]
    elif failure == "three":
        raw["new_beliefs"] = [new_belief(), new_belief(statement="Other")]
        raw["belief_revisions"] = [proposal(belief_id="b1").model_dump()]
    elif failure == "old_union":
        raw["interpretations"] = []
    else:
        del raw["belief_revisions"]
    with pytest.raises(ValidationError):
        Draft.model_validate(raw)


@pytest.mark.parametrize("failure", ["source", "quote", "belief", "subject"])
def test_wire_simplification_never_weakens_source_or_subject_allowlists(failure):
    value = accept(heard(), [proposal()])
    window = appraisal_context.build(value)
    raw = wire_proposal()
    candidate = proposal(belief_id="foreign" if failure == "belief" else "b1").model_dump()
    if failure == "source":
        candidate["citations"][0]["source_id"] = "foreign-source"
    if failure == "quote":
        candidate["citations"][0]["quote"] = "A fabricated completion"
    raw["belief_revisions"] = [candidate]
    if failure == "subject":
        raw["belief_revisions"] = []
        raw["new_beliefs"] = [new_belief(about_id="hidden-person")]
    result = Draft.model_validate(raw).materialize(motivation.build(value, [], window))
    with pytest.raises(ChpmError):
        appraisal.accept(value, result.interpretations, window, message_id="next")


def test_wire_schema_is_unambiguous_and_identifiers_remain_bound():
    schema = response_schema(Draft, {"belief_id": ["b1"], "about_id": ["@player"]})
    assert {"new_beliefs", "belief_revisions"} <= set(schema["required"])
    assert "interpretations" not in schema["properties"]
    assert "belief_id" not in schema["$defs"]["NewBelief"]["properties"]
    revision = schema["$defs"]["Revision"]["properties"]
    assert revision["belief_id"]["enum"] == ["b1"]
    assert not {"about_id", "statement", "domain"} & revision.keys()
