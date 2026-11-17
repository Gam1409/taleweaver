"""Missing proposal fields retain their typed contract through one bounded repair."""

import json
from copy import deepcopy
from types import SimpleNamespace

import pytest

from backend.engine.chpm import inference, proposal_attempt, proposal_repair
from backend.engine.chpm.errors import RecoverableChpmError
from backend.engine.chpm.proposal_draft import Draft
from backend.engine.chpm.schema import Decision, Settings, Usage
from tests.chpm_repair_fixture import corrections
from tests.test_chpm_json_schema_references import resolved
from tests.test_chpm_kernel import wire_proposal
from tests.test_chpm_proposal_repair_context import accept_choice
from tests.test_chpm_reliability import Replies

IDENTIFIERS = {"motive_id": ["goal1", "character"], "motive_ids": ["goal1", "character"]}


def missing_candidate_fields():
    original = wire_proposal()
    candidate = original["candidates"]["CONTINUE"]
    candidate["plan"] = candidate.pop("intention")
    candidate["motives"] = [{"id": "goal1", "support": True, "relevance": "Keep bridges safe."}]
    return original


@pytest.mark.parametrize("motive_id", ["goal1", "invented"])
async def test_nested_shape_repair_receives_bound_fields_and_rechecks_semantic_sources(motive_id):
    original = missing_candidate_fields()
    before = deepcopy(original)
    corrected = wire_proposal()["candidates"]["CONTINUE"]
    corrected["motives"][0]["motive_id"] = motive_id
    model = Replies([json.dumps(original), corrections(("/candidates/CONTINUE", corrected))])
    manager = SimpleNamespace(_chpm_model_factory=lambda _role: model, game_id="fixture")
    usage = Usage()
    request = proposal_attempt.request(
        manager,
        Settings(mode="live", actor_ids=["npc"], max_input_chars=64000),
        usage,
        "Use the schema.",
        {"authored_character": "Independent engineer"},
        Draft,
        IDENTIFIERS,
        accept_choice,
    )
    if motive_id == "invented":
        with pytest.raises(RecoverableChpmError, match="remains invalid"):
            await request
    else:
        decision = await request
        assert decision.selected.intention == corrected["intention"]
        assert Decision.model_validate_json(decision.model_dump_json()) == decision

    _, system, payload = model.requests[1]
    feedback = payload["proposal_feedback"]
    contract = feedback["original_response_schema"]
    intent = contract["$defs"]["Intent"]
    motive = contract["$defs"]["Motive"]
    assert "message_plan" in intent["required"]
    assert {"motive_id", "effect", "relevance"} <= set(motive["required"])
    assert motive["properties"]["motive_id"]["enum"] == IDENTIFIERS["motive_id"]
    assert motive["properties"]["effect"]["enum"] == ["supports", "tension"]
    assert feedback["repair_mode"] == "field_edits"
    assert "listed parent" in feedback["instruction"]
    assert feedback["rejected_proposal"] == original == before
    assert payload["authored_character"] == "Independent engineer"
    assert len(system) + len(json.dumps(payload, separators=(",", ":"))) <= 64000
    assert usage.calls == 2 and usage.proposal_repairs == 1


def test_missing_field_contract_falls_back_to_full_schema_within_the_same_input_budget():
    original = missing_candidate_fields()
    context = {"authored_character": "Independent engineer"}
    full = proposal_repair.payload_for(
        context,
        Draft,
        "Field required",
        original,
        instruction="Use the schema.",
        identifiers=IDENTIFIERS,
        limit=64000,
    )
    system, content = inference.compose("Use the schema.", full, Draft, IDENTIFIERS)
    limit = len(system) + len(content) + 500

    prepared = proposal_repair.prepare(
        context,
        Draft,
        "Field required",
        original,
        instruction="Use the schema.",
        identifiers=IDENTIFIERS,
        limit=limit,
    )

    assert prepared.original is None
    assert prepared.payload["proposal_feedback"]["rejected_proposal"] == original
    assert prepared.payload["authored_character"] == context["authored_character"]
    system, content = inference.compose("Use the schema.", prepared.payload, Draft, IDENTIFIERS)
    assert len(system) + len(content) <= limit
    contract = json.loads(system.split("JSON schema:\n", 1)[1])
    candidates = resolved(contract, contract["properties"]["candidates"])
    assert "message_plan" in candidates["additionalProperties"]["required"]
