"""Allowlisted wire aliases do not relax identity, evidence or semantic checks."""

import json
from copy import deepcopy

import pytest

from backend.engine.chpm import inference, proposal_attempt
from backend.engine.chpm.json_contract import response_schema
from backend.engine.chpm.proposal_draft import Draft
from backend.engine.chpm.schema import Settings, Usage
from tests.test_chpm_json_contract import host
from tests.test_chpm_kernel import wire_proposal
from tests.test_chpm_proposal_repair_context import accept_choice
from tests.test_chpm_reliability import Replies


async def test_known_singular_choice_id_needs_no_model_retry():
    original = wire_proposal()
    raw = deepcopy(original)
    raw["choice"]["motive_id"] = raw["choice"].pop("motive_ids")[0]
    manager, usage = host(json.dumps(raw)), Usage()
    result = await inference.request(
        manager,
        Settings(),
        usage,
        "Use the schema.",
        {},
        Draft,
        "proposal",
        identifiers={"motive_ids": ["goal1", "character"]},
    )
    assert result.model_dump() == Draft.model_validate(original).model_dump()
    assert usage.calls == 1 and usage.proposal_repairs == 0
    assert usage.format_repairs == 1
    assert manager._chpm_model_factory("small").aexecute_simple_task.await_count == 1
    assert raw["choice"]["motive_id"] == "goal1" and "motive_ids" not in raw["choice"]


@pytest.mark.parametrize("value", [None, True, 1, [], ["goal1"], "", "Goal1", "unknown"])
async def test_ambiguous_or_unknown_alias_is_not_repaired(value):
    raw = wire_proposal()
    raw["choice"].pop("motive_ids")
    raw["choice"]["motive_id"] = value
    usage = Usage()
    with pytest.raises(inference.InvalidResponseError):
        await inference.request(
            host(json.dumps(raw)),
            Settings(),
            usage,
            "Use the schema.",
            {},
            Draft,
            "proposal",
            identifiers={"motive_ids": ["goal1"]},
        )
    assert getattr(usage, "format_repairs", 0) == 0


async def test_conflicting_alias_and_canonical_field_are_never_silently_chosen():
    raw = wire_proposal()
    raw["choice"]["motive_id"] = "character"
    with pytest.raises(inference.InvalidResponseError):
        await inference.request(
            host(json.dumps(raw)),
            Settings(),
            Usage(),
            "Use the schema.",
            {},
            Draft,
            "proposal",
            identifiers={"motive_ids": ["goal1", "character"]},
        )


async def test_local_format_correction_cannot_bypass_semantic_grounding():
    original = wire_proposal()
    original["choice"]["motive_id"] = "character"
    original["choice"].pop("motive_ids")
    model = Replies([json.dumps(original), json.dumps(wire_proposal())])
    manager = host("")
    manager._chpm_model_factory = lambda _role: model
    usage = Usage()
    decision = await proposal_attempt.request(
        manager,
        Settings(mode="live", actor_ids=["npc"], max_calls_per_turn=6),
        usage,
        "Use the schema.",
        {},
        Draft,
        {"motive_ids": ["goal1", "character"]},
        accept_choice,
    )
    assert decision.choice_preference.motive_ids == ["goal1"]
    assert usage.calls == 2 and usage.proposal_repairs == 1 and usage.format_repairs == 1
    assert "Uncited motive IDs" in usage.proposal_feedback[0]


def test_finite_candidate_maps_use_explicit_optional_properties():
    contract = response_schema(Draft, None, explicit_keys=True)
    candidates = contract["properties"]["candidates"]
    assert set(candidates["properties"]) == {
        "CONTINUE",
        "INITIATE",
        "ACCEPT",
        "REFUSE",
        "NEGOTIATE",
        "CLARIFY",
        "DEFER",
    }
    assert candidates["additionalProperties"] is False
    assert candidates.get("required", []) == []
    assert (candidates["minProperties"], candidates["maxProperties"]) == (2, 4)
    assert all(value == {"$ref": "#/$defs/Intent"} for value in candidates["properties"].values())
    assert "properties" not in Draft.model_json_schema()["properties"]["candidates"]


def test_transport_schema_expansion_does_not_expand_the_model_prompt():
    prompt, _ = inference.compose("Use the schema.", {}, Draft, None)
    compact = response_schema(Draft, None)
    expanded = response_schema(Draft, None, explicit_keys=True)
    assert "properties" not in compact["properties"]["candidates"]
    assert prompt.endswith(json.dumps(compact, ensure_ascii=False, separators=(",", ":")))
    assert len(json.dumps(compact)) < len(json.dumps(expanded))


def test_legacy_usage_loads_without_a_new_schema_version():
    usage = Usage.model_validate({"calls": 1, "proposal_repairs": 0})
    assert usage.format_repairs == 0
    assert Usage.model_validate_json(usage.model_dump_json()) == usage
