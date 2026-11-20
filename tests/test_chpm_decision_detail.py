"""Compact live choices use the same grounding, clarification and replay boundaries."""

import json
from copy import deepcopy
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from backend.engine.chpm import cognition
from backend.engine.chpm.proposal_references import ReferenceDraft
from backend.engine.chpm.schema import Decision, Settings, Usage
from backend.engine.chpm.template_settings import Defaults
from tests.test_chpm_host_state import mind
from tests.test_chpm_kernel import observation, wire_proposal
from tests.test_chpm_reliability import Replies


def proposal(preferred):
    body = wire_proposal()
    selected = body["candidates"]["CONTINUE"]
    body["candidates"] = {preferred: selected}
    body["choice"]["preferred"] = preferred
    if preferred == "CLARIFY":
        body["candidates"].update(ACCEPT=deepcopy(selected), REFUSE=deepcopy(selected))
        body["question_gate"] = {
            "kind": "external_fact",
            "missing_fact": "Which route is open?",
            "branches": [
                {"answer": "North", "action": "ACCEPT"},
                {"answer": "South", "action": "REFUSE"},
            ],
        }
    return body


def test_detail_defaults_and_round_trips_in_sessions_and_templates():
    for schema in (Settings, Defaults):
        assert schema().decision_detail == "full"
        assert "decision_detail" not in schema().model_dump()
        value = schema(decision_detail="compact")
        assert schema.model_validate_json(value.model_dump_json()).decision_detail == "compact"
        with pytest.raises(ValidationError):
            schema(decision_detail="unknown")


@pytest.mark.parametrize("chosen", ["CONTINUE", "DEFER", "CLARIFY"])
async def test_staged_compact_decision_can_publish_one_intention_or_a_grounded_question(chosen):
    model = Replies([json.dumps(proposal(chosen))])
    manager = SimpleNamespace(game_id="session", _chpm_model_factory=lambda _role: model)
    decision, _ = await cognition.deliberate(
        manager,
        Settings(mode="live", actor_ids=["npc"], decision_detail="compact"),
        Usage(),
        "npc",
        observation(),
        {"authored_goal": "Repair the bridge"},
        [],
        mind(),
    )
    assert decision.selected.kind == chosen
    assert set(decision.candidate_motives) == (
        {chosen, "ACCEPT", "REFUSE"} if chosen == "CLARIFY" else {chosen}
    )
    assert Decision.model_validate_json(decision.model_dump_json()) == decision
    assert len(model.requests) == 1
    assert "2-4 distinct next intentions" not in model.requests[0][1]


def test_compact_wire_rejects_missing_extra_and_unrelated_candidates():
    from backend.engine.chpm.compact_decision import schema_for

    schema = schema_for(ReferenceDraft)
    body = proposal("CLARIFY")
    body["reference_scope"] = "scope"
    for candidate in body["candidates"].values():
        candidate.pop("goal_alignment", None)
        candidate.pop("goal_quote", None)
        candidate["agenda_change"] = None
    schema.model_validate(body)
    del body["candidates"]["REFUSE"]
    with pytest.raises(ValidationError, match="two branch candidates"):
        schema.model_validate(body)
    body["choice"]["preferred"] = "ACCEPT"
    with pytest.raises(ValidationError, match="only the preferred candidate"):
        schema.model_validate(body)
    del body["candidates"]["CLARIFY"], body["question_gate"]
    schema.model_validate(body)
    with pytest.raises(ValidationError):
        ReferenceDraft.model_validate(body)
