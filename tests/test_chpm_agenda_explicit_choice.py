"""Modern proposals explicitly choose a spoken agenda change or null per candidate."""

import json
from copy import deepcopy

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from backend.engine.chpm import inference, json_contract, proposal_edits, proposal_references
from backend.engine.chpm.proposal_draft import Draft
from backend.engine.chpm.schema import Decision, KernelState, ProposalOptions, Settings, Usage
from tests.test_chpm_json_contract import host
from tests.test_chpm_kernel import decision, wire_proposal

SCHEMAS = (
    proposal_references.ReferenceDraft,
    proposal_references.ReferenceDevelopmentDraft,
    proposal_references.GoalReferenceProposal,
)


def response(schema):
    """Use raw modern wire objects so fixture migration cannot conceal an omission."""
    candidates = {
        kind: {
            "intention": intention,
            "preconditions": [],
            "reconsider_if": "The situation changes",
            "agenda_change": None,
        }
        for kind, intention in (("ACCEPT", "Acknowledge the message"), ("DEFER", "Wait"))
    }
    body = {"reference_scope": "scope", "candidates": candidates}
    if schema is proposal_references.GoalReferenceProposal:
        return {**body, "appraisal": "A response is possible"}
    for candidate in candidates.values():
        candidate["message_plan"] = candidate.pop("intention")
        candidate["motives"] = [
            {"motive_id": "character", "effect": "supports", "relevance": "Consider the request"}
        ]
    return {
        **body,
        "choice": {
            "preferred": "ACCEPT",
            "motive_ids": ["character"],
            "reason": "Acknowledge the request",
            "continuity": "new",
        },
        "new_beliefs": [],
        "belief_revisions": [],
    }


@pytest.mark.parametrize("schema", SCHEMAS)
@pytest.mark.parametrize("kind", ["ACCEPT", "DEFER"])
@pytest.mark.parametrize("explicit_keys", [False, True])
def test_omission_rejects_in_prompt_decoder_and_raw_model(schema, kind, explicit_keys):
    raw = response(schema)
    raw["candidates"][kind].pop("agenda_change")
    contract = json_contract.response_schema(schema, {}, explicit_keys=explicit_keys)

    errors = list(Draft202012Validator(contract).iter_errors(raw))

    assert len(errors) == 1
    assert errors[0].validator == "required"
    assert list(errors[0].path) == ["candidates", kind]
    with pytest.raises(ValidationError) as rejected:
        json_contract.parse(schema, json.dumps(raw))
    assert [(item["loc"], item["type"]) for item in rejected.value.errors()] == [
        (("candidates", kind, "agenda_change"), "missing")
    ]


@pytest.mark.parametrize("schema", SCHEMAS)
@pytest.mark.parametrize(
    "choice",
    [
        None,
        {"action": "goal", "text": "Keep the station informed"},
        {"action": "commitment", "text": "Keep watch over the radio"},
        {"action": "withdraw", "entry_id": "owned"},
        {"action": "report_done", "entry_id": "owned"},
    ],
)
def test_explicit_null_creation_and_id_only_closure_keep_their_wire_shapes(schema, choice):
    raw = response(schema)
    raw["candidates"]["ACCEPT"]["agenda_change"] = choice
    contract = json_contract.response_schema(schema, {"entry_id": ["owned"]}, explicit_keys=True)

    parsed = json_contract.parse(schema, json.dumps(raw))

    assert Draft202012Validator(contract).is_valid(raw)
    assert parsed.model_dump()["candidates"]["ACCEPT"]["agenda_change"] == choice
    assert parsed.candidates["DEFER"].agenda_change is None


@pytest.mark.parametrize("schema", SCHEMAS)
async def test_inference_exposes_missing_choice_without_filling_it_or_retrying(schema):
    raw = response(schema)
    raw["candidates"]["ACCEPT"].pop("agenda_change")
    manager, usage = host(json.dumps(raw)), Usage()

    with pytest.raises(inference.InvalidResponseError, match="ACCEPT.agenda_change") as rejected:
        await inference.request(
            manager, Settings(), usage, "Use the schema", {}, schema, "proposal"
        )

    assert rejected.value.candidate == raw
    assert "agenda_change" not in raw["candidates"]["ACCEPT"]
    assert usage.calls == 1 and usage.format_repairs == usage.proposal_repairs == 0
    assert manager._chpm_model_factory("small").aexecute_simple_task.await_count == 1


@pytest.mark.parametrize("schema", SCHEMAS)
def test_existing_field_repair_can_supply_the_missing_explicit_choice(schema):
    raw = response(schema)
    raw["candidates"]["ACCEPT"].pop("agenda_change")
    before = deepcopy(raw)
    path = "/candidates/ACCEPT/agenda_change"
    edits = proposal_edits.Corrections.model_validate(
        {"edits": [{"op": "replace", "path": path, "value": None}]}
    )

    assert path in proposal_edits.paths(raw, schema)
    corrected = proposal_edits.apply(raw, edits, schema)

    assert schema.model_validate(corrected).candidates["ACCEPT"].agenda_change is None
    assert raw == before


def test_legacy_producers_and_saved_decisions_retain_omitted_agenda_defaults():
    legacy = wire_proposal()
    for candidate in legacy["candidates"].values():
        candidate.pop("agenda_change")
    assert all(
        candidate.agenda_change is None
        for candidate in Draft.model_validate(legacy).candidates.values()
    )
    canonical = decision().model_dump(mode="json")
    canonical["selected"].pop("agenda_change")
    for candidate in canonical["proposal"]["candidates"]:
        candidate.pop("agenda_change")
    restored = Decision.model_validate_json(json.dumps(canonical))
    options = ProposalOptions.model_validate(
        {
            "appraisal": restored.proposal.appraisal,
            "candidates": {
                candidate["kind"]: {key: value for key, value in candidate.items() if key != "kind"}
                for candidate in canonical["proposal"]["candidates"]
            },
        }
    )
    state = KernelState(actors={"npc": restored})

    assert restored.selected.agenda_change is None
    assert all(candidate.agenda_change is None for candidate in options.candidates.values())
    assert KernelState.model_validate_json(state.model_dump_json()) == state
