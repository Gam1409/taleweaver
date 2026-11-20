"""Dense and sparse structural repairs receive complete, bounded parent guidance."""

import json
from copy import deepcopy
from types import SimpleNamespace
from typing import Literal

from pydantic import ValidationError, create_model

from backend.engine.chpm import (
    inference,
    proposal_attempt,
    proposal_edits,
    proposal_repair,
    proposal_repair_groups,
)
from backend.engine.chpm.proposal_draft import Draft
from backend.engine.chpm.schema import Settings, Usage
from tests.chpm_repair_fixture import corrections
from tests.test_chpm_kernel import wire_proposal
from tests.test_chpm_reliability import Replies

IDENTIFIERS = {
    "motive_id": ["goal1", "character"],
    "motive_ids": ["goal1", "character"],
    "source_id": ["e1"],
    "about_id": ["B"],
}


def dense_proposal():
    corrected = wire_proposal()
    corrected["experiences"] = []
    corrected["new_beliefs"] = [
        {
            "about_id": "B",
            "domain": "boundaries",
            "statement": "The partner requested help inspecting the bridge.",
            "stance": "support",
            "citations": [{"source_id": "e1", "quote": "Help inspect the bridge."}],
            "alternatives": ["The request could be a preliminary suggestion."],
            "unknowns": ["The partner's reason is unknown."],
        }
    ]
    for candidate in corrected["candidates"].values():
        candidate["motives"] = [
            {"motive_id": "goal1", "effect": "supports", "relevance": "Inspect the bridge."},
            {"motive_id": "character", "effect": "supports", "relevance": "Consider the request."},
        ]
    rejected = deepcopy(corrected)
    rejected["new_beliefs"][0].update(
        domain="intent", stance="supported", citations=["e1: Help inspect the bridge."]
    )
    for candidate in rejected["candidates"].values():
        candidate.pop("reconsider_if")
        candidate["motives"] = [
            {"id": motive["motive_id"], "role": "support"} for motive in candidate["motives"]
        ]
    return rejected, corrected


def sparse_proposal():
    corrected = wire_proposal()
    corrected["experiences"] = [
        {
            "channel": "need_satisfaction",
            "dimension": "competence",
            "about_id": None,
            "level": "low",
            "citations": [{"source_id": "e1", "quote": "Help inspect the bridge."}],
            "personal_motive_ids": ["character"],
            "explanation": "The request provides a familiar practical task.",
            "alternatives": ["The task may require more preparation."],
            "unknowns": ["The bridge's current condition is unknown."],
        }
    ]
    rejected = deepcopy(corrected)
    rejected["experiences"][0].update(explanation="x" * 181, alternatives=[{"source_id": "e1"}])
    rejected["experiences"][0].pop("unknowns")
    return rejected, corrected


def prepare(candidate):
    try:
        Draft.model_validate(candidate)
    except ValidationError as exc:
        feedback = inference.validation_feedback(exc)
        error_count = exc.error_count()
    return (
        proposal_repair.prepare(
            {"pinned_identity": "An independent craftsperson."},
            Draft,
            feedback,
            candidate,
            instruction="Use the grounded proposal contract.",
            identifiers=IDENTIFIERS,
            limit=64000,
        ),
        error_count,
    )


def test_dense_repair_reports_all_twenty_six_errors_in_three_existing_parent_groups():
    candidate, _ = dense_proposal()
    before = deepcopy(candidate)
    prepared, error_count = prepare(candidate)
    feedback = prepared.payload["proposal_feedback"]
    groups = feedback["recommended_repair_groups"]
    assert error_count == feedback["structural_error_count"] == 26
    assert feedback["max_edits"] == 8
    assert [group["path"] for group in groups] == [
        "/candidates/CONTINUE",
        "/candidates/DEFER",
        "/new_beliefs/0",
    ]
    issues = [issue for group in groups for issue in group["issues"]]
    assert len(issues) == 26
    assert {issue["type"] for issue in issues} == {
        "literal_error",
        "model_type",
        "too_short",
        "missing",
        "extra_forbidden",
    }
    assert all(group["path"] in prepared.identifiers["path"] for group in groups)
    assert "/candidates/CONTINUE/reconsider_if" in prepared.identifiers["path"]
    motive = feedback["original_response_schema"]["$defs"]["Motive"]
    assert motive["properties"]["motive_id"]["enum"] == IDENTIFIERS["motive_id"]
    assert candidate == before == feedback["rejected_proposal"]


async def test_grouped_repair_preserves_unedited_choice_and_uses_only_the_existing_retry():
    candidate, corrected = dense_proposal()
    before = deepcopy(candidate)
    changes = [
        ("/new_beliefs/0", corrected["new_beliefs"][0]),
        *(("/candidates/" + key, value) for key, value in corrected["candidates"].items()),
    ]
    model = Replies([json.dumps(candidate), corrections(*changes)])
    manager = SimpleNamespace(_chpm_model_factory=lambda _role: model, game_id="fixture")
    usage = Usage()
    result = await proposal_attempt.request(
        manager,
        Settings(mode="live", actor_ids=["npc"], max_input_chars=64000),
        usage,
        "Use the grounded proposal contract.",
        {"pinned_identity": "An independent craftsperson."},
        Draft,
        IDENTIFIERS,
        lambda draft: draft,
    )
    assert result == Draft.model_validate(corrected)
    assert result.choice.model_dump(mode="json") == candidate["choice"]
    assert result.experiences == []
    assert candidate == before
    assert usage.calls == 2 and usage.proposal_repairs == 1
    assert model.requests[1][2]["proposal_feedback"]["structural_error_count"] == 26


def test_sparse_missing_experience_child_has_a_complete_allowed_parent_group():
    candidate, _ = sparse_proposal()
    prepared, error_count = prepare(candidate)
    feedback = prepared.payload["proposal_feedback"]
    groups = feedback["recommended_repair_groups"]
    assert error_count == feedback["structural_error_count"] == 3
    assert [group["path"] for group in groups] == ["/experiences/0"]
    assert {issue["path"] for issue in groups[0]["issues"]} == {
        "/experiences/0/explanation",
        "/experiences/0/alternatives/0",
        "/experiences/0/unknowns",
    }
    assert "/experiences/0/unknowns" in prepared.identifiers["path"]


async def test_sparse_child_edits_add_only_the_declared_missing_field_in_one_retry():
    candidate, corrected = sparse_proposal()
    original = deepcopy(candidate)
    changes = [
        ("/experiences/0/" + field, corrected["experiences"][0][field])
        for field in ("explanation", "alternatives", "unknowns")
    ]
    model = Replies([json.dumps(candidate), corrections(*changes)])
    manager = SimpleNamespace(_chpm_model_factory=lambda _role: model, game_id="fixture")
    usage = Usage()
    result = await proposal_attempt.request(
        manager,
        Settings(mode="live", actor_ids=["npc"], max_input_chars=64000),
        usage,
        "Use the grounded proposal contract.",
        {},
        Draft,
        IDENTIFIERS,
        lambda draft: draft,
    )
    assert result == Draft.model_validate(corrected)
    assert result.choice.model_dump(mode="json") == candidate["choice"]
    assert candidate == original
    assert usage.calls == 2 and usage.proposal_repairs == 1
    assert proposal_edits.Corrections.model_json_schema()["properties"]["edits"]["maxItems"] == 8


def test_more_structural_issues_than_the_existing_path_bound_selects_full_response():
    candidate = wire_proposal()
    candidate.update({"extra_" + str(index): "unvalidated" for index in range(257)})
    original = deepcopy(candidate)
    prepared, error_count = prepare(candidate)
    assert error_count == 257
    assert prepared.original is None
    assert "repair_mode" not in prepared.payload["proposal_feedback"]
    assert prepared.payload["proposal_feedback"]["rejected_proposal"] == original == candidate
    assert prepared.payload["pinned_identity"] == "An independent craftsperson."


def test_recommendation_groups_never_suggest_more_than_the_existing_eight_edit_budget():
    for count in (8, 9):
        schema = create_model(
            "BoundedRoots", **{f"field_{index}": (str, ...) for index in range(count)}
        )
        candidate = {f"field_{index}": 1 for index in range(count)}
        report = proposal_repair_groups.inspect(
            candidate, schema, proposal_edits.paths(candidate, schema)
        )
        if count == 9:
            assert report is None
            continue
        assert report is not None and report.error_count == count
        assert len(report.groups) == 8


def test_grouped_constraints_remain_actionable_after_the_four_error_summary():
    _, candidate = dense_proposal()
    candidate["choice"].update(
        preferred="not_an_action", motive_ids=[], reason="x" * 301, continuity="not_a_mode"
    )
    candidate["new_beliefs"][0]["domain"] = "unknown_domain"
    prepared, error_count = prepare(candidate)
    feedback = prepared.payload["proposal_feedback"]
    assert error_count == feedback["structural_error_count"] == 5
    issue = next(
        issue
        for group in feedback["recommended_repair_groups"]
        for issue in group["issues"]
        if issue["path"] == "/new_beliefs/0/domain"
    )
    assert issue["type"] == "literal_error"
    assert all(
        value in issue["message"]
        for value in ("reliability", "competence", "benevolence", "affection", "boundaries")
    )
    assert "unknown_domain" not in json.dumps(feedback["recommended_repair_groups"])
    assert all(
        "input" not in item and "ctx" not in item
        for group in feedback["recommended_repair_groups"]
        for item in group["issues"]
    )


def test_oversized_constraint_messages_use_the_complete_response_fallback():
    schema = create_model("LongConstraint", value=(Literal["x" * 601, "short"], ...))
    candidate = {"value": "invalid"}
    assert (
        proposal_repair_groups.inspect(candidate, schema, proposal_edits.paths(candidate, schema))
        is None
    )
