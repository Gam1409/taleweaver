"""Wire choices and correction feedback match the retained-intention contract."""

import json
from copy import deepcopy
from types import SimpleNamespace

import pytest

from backend.engine.chpm import cognitive_context, proposal_attempt
from backend.engine.chpm.json_contract import response_schema
from backend.engine.chpm.proposal_draft import Draft
from backend.engine.chpm.schema import Settings, Usage
from tests.test_chpm_appraisal import heard
from tests.test_chpm_bounded_proposal_edits import tight_request
from tests.test_chpm_kernel import observation, wire_proposal
from tests.test_chpm_proposal_repair_context import accept_choice
from tests.test_chpm_reliability import Replies
from tests.test_chpm_semantic_choice import fixture, prior


@pytest.mark.parametrize("retained", [False, True])
def test_wire_contract_cannot_claim_transition_grounds_without_a_retained_intention(retained):
    value, _, _, _ = fixture()
    value = heard(value, message="input", text="The bridge is ready.")
    previous = prior().model_dump() if retained else None
    _, _, payload, identifiers = cognitive_context.pack(
        value,
        observation(),
        {"previous_intention": previous},
        [],
        Settings(),
        "Use the schema.",
        wire_schema=Draft,
    )
    contract = response_schema(Draft, identifiers)
    choice = contract["$defs"]["ChoicePreference"]["properties"]
    assert payload["previous_intention"] == previous
    if retained:
        assert set(choice["continuity"]["enum"]) == {"new", "maintain", "revise"}
        assert choice["change_basis"]["maxItems"] > 0
    else:
        assert choice["continuity"]["enum"] == ["new"]
        assert choice["change_basis"]["maxItems"] == 0
    assert (
        Draft.model_json_schema()["$defs"]["ChoicePreference"]["properties"]["change_basis"][
            "maxItems"
        ]
        > 0
    )


@pytest.mark.parametrize("structural", [False, True])
async def test_single_correction_names_the_exact_empty_transition_field(structural):
    original = wire_proposal()
    original["choice"]["change_basis"] = [{"source_id": "e1", "quote": "The bridge is ready."}]
    if structural:
        original["choice"]["reason"] = "x" * 301
    corrected = deepcopy(original)
    corrected["choice"].update(change_basis=[], reason="Keep my purpose.")
    model = Replies([json.dumps(original), json.dumps(corrected)])
    manager = SimpleNamespace(_chpm_model_factory=lambda _role: model, game_id="fixture")
    usage = Usage()

    decision = await proposal_attempt.request(
        manager,
        Settings(mode="live", actor_ids=["npc"]),
        usage,
        "Use the schema.",
        {"previous_intention": None},
        Draft,
        {},
        accept_choice,
    )

    feedback = model.requests[1][2]["proposal_feedback"]["error"]
    assert "choice.change_basis=[]" in feedback
    assert "choice.continuity" in feedback
    assert decision.choice_preference.change_basis == []
    assert original["choice"]["change_basis"]
    assert usage.calls == 2 and usage.proposal_repairs == 1


async def test_continuity_correction_also_works_with_bounded_field_edits():
    original = wire_proposal()
    original["choice"]["change_basis"] = [{"source_id": "e1", "quote": "The bridge is ready."}]
    context, settings = tight_request(original)
    context["previous_intention"] = None
    edits = {"edits": [{"op": "replace", "path": "/choice/change_basis", "value": []}]}
    model = Replies([json.dumps(original), json.dumps(edits)])
    manager = SimpleNamespace(_chpm_model_factory=lambda _role: model, game_id="fixture")
    usage = Usage()

    decision = await proposal_attempt.request(
        manager, settings, usage, "Use the schema.", context, Draft, {}, accept_choice
    )

    feedback = model.requests[1][2]["proposal_feedback"]
    assert feedback["repair_mode"] == "field_edits"
    assert "choice.change_basis=[]" in feedback["error"]
    assert decision.choice_preference.change_basis == []
    assert usage.calls == 2 and usage.proposal_repairs == 1
