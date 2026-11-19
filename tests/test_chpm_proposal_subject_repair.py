"""One bounded correction distinguishes subjects of an appraisal from actionable items."""

from copy import deepcopy

import pytest

from backend.engine.chpm import json_contract, proposal_edits, proposal_repair
from tests.test_chpm_experience_wire_schema import experience
from tests.test_chpm_reference_boundaries import prepare, response


def setup_case():
    _, _, prepared = prepare()
    candidate = response(prepared)
    candidate["new_beliefs"] = [
        {
            "about_id": "@player",
            "domain": "reliability",
            "statement": "The report is credible.",
            "stance": "support",
            "citations": [{"fragment_id": next(iter(prepared.references.quotes))}],
            "alternatives": [],
            "unknowns": [],
        }
    ]
    candidate["experiences"] = [experience(about_id="CUP")]
    return prepared, candidate


def test_one_repair_points_to_item_misused_as_affect_target_alongside_motive_and_shape():
    prepared, candidate = setup_case()
    candidate["choice"]["reason"] = "x" * 301
    before = deepcopy(candidate)
    # Object handles can be available to world actions without becoming appraisal subjects.
    ids = {**prepared.identifiers, "item_id": ["CUP"]}
    with pytest.raises(ValueError, match="/experiences/0/about_id"):
        json_contract.validate_identifiers(prepared.schema, candidate, ids)
    result = proposal_repair.prepare(
        prepared.payload,
        prepared.schema,
        "CHPM about_id selects an unavailable identifier.",
        candidate,
        instruction=prepared.instruction,
        identifiers=ids,
        limit=64000,
        motive_errors=[
            {
                "loc": ("candidates", "DEFER", "motives"),
                "type": "motive_own_support",
                "msg": "Cite a supporting motive.",
            }
        ],
    )
    feedback = result.payload["proposal_feedback"]
    groups = feedback["recommended_repair_groups"]
    issues = {issue["path"]: issue for group in groups for issue in group["issues"]}
    path = "/experiences/0/about_id"
    assert {path, "/choice/reason", "/candidates/DEFER/motives"} == set(issues)
    assert issues[path]["type"] == "unavailable_subject"
    assert "@player" in issues[path]["message"] and "null" in issues[path]["message"]
    assert "CUP" not in issues[path]["message"]
    assert path in result.identifiers["path"] and result.original == candidate == before
    corrections = proposal_edits.Corrections.model_validate(
        {
            "edits": [
                {"op": "replace", "path": path, "value": None},
                {"op": "replace", "path": "/choice/reason", "value": "Consider the report."},
            ]
        }
    )
    fixed = proposal_edits.apply(candidate, corrections, prepared.schema)
    prepared.schema.model_validate(fixed)
    json_contract.validate_identifiers(prepared.schema, fixed, ids)
    assert fixed["new_beliefs"][0]["about_id"] == "@player"
    assert candidate == before and ids["item_id"] == ["CUP"]


@pytest.mark.parametrize(
    "field,expected,excluded",
    [
        ("new_beliefs", "@player", "null"),
        ("need", "null", "@player"),
    ],
)
def test_full_and_field_repairs_offer_only_the_subject_values_legal_for_this_field(
    field,
    expected,
    excluded,
):
    prepared, candidate = setup_case()
    candidate["experiences"] = []
    if field == "need":
        candidate["experiences"] = [experience("need_satisfaction", "autonomy", "CUP")]
        path = "/experiences/0/about_id"
    else:
        candidate[field][0]["about_id"] = "CUP"
        path = "/new_beliefs/0/about_id"
    for limit in (64000, 1):
        result = proposal_repair.prepare(
            prepared.payload,
            prepared.schema,
            "Invalid subject.",
            candidate,
            instruction=prepared.instruction,
            identifiers=prepared.identifiers,
            limit=limit,
        )
        feedback = result.payload["proposal_feedback"]
        if result.original is None:
            issues = feedback["subject_errors"]
        else:
            issues = [i for g in feedback["recommended_repair_groups"] for i in g["issues"]]
        message = next(i["message"] for i in issues if i["path"] == path)
        assert expected in message and excluded not in message
