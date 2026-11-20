"""Motive feedback remains complete, observer-bound and safe for malformed wire data."""

from copy import deepcopy

import pytest

from backend.engine.chpm import inference, motivation, motivation_diagnostics, proposal_repair
from backend.engine.chpm.appraisal_contracts import GroundedProposal
from backend.engine.chpm.kernel import ChpmError
from backend.engine.chpm.proposal_draft import Draft
from tests.test_chpm_motivation import candidates, catalogue, motive
from tests.test_chpm_motive_repair_groups import proposals


def test_resolver_reports_both_candidates_and_independent_faults_without_mutating_sources():
    raw = candidates(motives=[motive("unknown", "tension")] * 2).model_dump(mode="json")
    raw["candidates"]["DEFER"]["motives"][0]["effect"] = "tension"
    sources = catalogue()
    before = sources.payload()
    with pytest.raises(ChpmError) as caught:
        motivation.resolve(GroundedProposal.model_validate(raw), sources)

    message = str(caught.value)
    assert "repeat" in message and "unavailable" in message and "goal alignment" in message
    assert "ACCEPT lacks a supporting" in message and "DEFER lacks a supporting" in message
    assert sources.payload() == before


@pytest.mark.parametrize("malformed", [None, [], {}, 42, "unsupported"])
def test_malformed_effect_does_not_hide_another_candidate_or_raise_during_diagnosis(malformed):
    original, _, _ = proposals("key")
    original["candidates"]["REFUSE"]["motives"][0].update(motive_id="unavailable", effect=malformed)
    before = deepcopy(original)
    errors = motivation_diagnostics.inspect(original, catalogue())

    assert {(error["loc"][1], error["type"]) for error in errors} == {
        ("REFUSE", "motive_unavailable"),
        ("DEFER", "motive_own_support"),
    }
    assert original == before


def test_missing_relevance_does_not_hide_known_source_and_support_faults():
    original, _, _ = proposals("key", intra=True)
    original["candidates"]["REFUSE"]["motives"][0].pop("relevance")
    errors = motivation_diagnostics.inspect(original, catalogue())

    assert len(errors) == 5
    assert {error["type"] for error in errors} == {
        "motive_unavailable",
        "motive_duplicate",
        "motive_own_support",
    }


@pytest.mark.parametrize("malformed", [None, [], {str(index): {} for index in range(10000)}])
def test_diagnostics_do_not_traverse_outside_the_existing_candidate_bound(malformed):
    assert motivation_diagnostics.inspect({"candidates": malformed}, catalogue()) == []


def test_retired_wire_goal_fields_do_not_create_semantic_faults():
    original, _, _ = proposals("key")
    original["candidates"]["CONTINUE"].update(
        goal_alignment="conflicts", goal_quote="Fabricated obsolete wire value"
    )

    errors = motivation_diagnostics.inspect(original, catalogue())

    assert len(errors) == 2
    assert {error["type"] for error in errors} == {"motive_own_support"}


def test_current_catalogue_cannot_promote_report_or_foreign_character_to_own_support():
    original, _, _ = proposals("key")
    sources = catalogue()
    sources.sources["character"] = sources.sources["character"].model_copy(
        update={"subject_id": "another-actor"}
    )
    sources.sources["goal1"] = sources.sources["goal1"].model_copy(update={"status": "reported"})

    errors = motivation_diagnostics.inspect(original, sources)

    assert {error["loc"][1] for error in errors if error["type"] == "motive_own_support"} == {
        "CONTINUE",
        "REFUSE",
        "DEFER",
    }


def test_full_response_fallback_retains_all_motive_faults_without_expanding_input_budget():
    original, _, _ = proposals("key", intra=True)
    original["candidates"]["REFUSE"].pop("intention")
    errors = motivation_diagnostics.inspect(original, catalogue())
    payload = {"pinned_identity": "Independent craftsperson."}
    identifiers = {"motive_id": ["character", "goal1"]}
    options = {"instruction": "Use the schema.", "identifiers": identifiers}
    full = proposal_repair.payload_for(
        payload, Draft, "Invalid proposal.", original, limit=64000, motive_errors=errors, **options
    )
    prompt, content = inference.compose(options["instruction"], full, Draft, identifiers)
    limit = len(prompt) + len(content)

    prepared = proposal_repair.prepare(
        payload, Draft, "Invalid proposal.", original, limit=limit, motive_errors=errors, **options
    )

    assert prepared.original is None
    feedback = prepared.payload["proposal_feedback"]
    assert feedback["motive_error_count"] == len(feedback["motive_errors"]) == 5
    assert {item["path"] for item in feedback["motive_errors"]} == {
        "/candidates/REFUSE/motives/0/motive_id",
        "/candidates/REFUSE/motives/1/motive_id",
        "/candidates/REFUSE/motives",
        "/candidates/DEFER/motives",
    }
    assert prepared.payload["pinned_identity"] == payload["pinned_identity"]
    prompt, content = inference.compose(
        options["instruction"], prepared.payload, Draft, identifiers
    )
    assert len(prompt) + len(content) == limit
