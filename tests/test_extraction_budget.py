"""Dense-turn limits remain bounded and omissions are visible without another call."""

import pytest
from jsonschema import Draft202012Validator

from backend.engine.narrated_items import coverage, reference_schema
from backend.engine.narrated_items.response_sections import read
from backend.engine.narrated_items.schema import ItemExtraction, SharedItemExtraction
from backend.engine.physical_conditions.schema import MAX_PROPOSALS
from tests.test_extraction_coverage import catalog


def dense_response(count=MAX_PROPOSALS):
    source = catalog("\n".join(f"Panel {n} becomes warm." for n in range(MAX_PROPOSALS + 1)))
    refs = list(source.narration_passages)
    proposals = [
        {
            "operation": "record",
            "target_id": f"PANEL-{n}",
            "kind": "item_state",
            "part": "temperature",
            "detail": f"Panel {n} becomes warm.",
            "evidence": ref,
        }
        for n, ref in enumerate(refs[:count])
    ]
    tags = {f"c{n}": ["conditions"] for n in range(count)}
    tags.update({f"c{n}": ["conditions_deferred"] for n in range(count, len(refs))})
    return source, {
        "actions": [],
        "scene_updates": [],
        "final_frame_actions": [],
        "movements": [],
        "condition_updates": proposals,
        "coverage": tags,
    }


def test_explicit_deferral_at_capacity_keeps_all_valid_proposals_and_reports_budget():
    source, response = dense_response()
    body, audit = coverage.inspect(SharedItemExtraction(**response), source, staging=False)
    assert len(body["condition_updates"]) == MAX_PROPOSALS
    assert audit.status == "needs_review" and not audit.blocked
    assert audit.issues == (
        {"group": "c12", "reason": "budget_deferred", "domains": ["conditions"]},
    )
    assert audit.payload()["condition_budget"] == {
        "limit": MAX_PROPOSALS,
        "proposed": MAX_PROPOSALS,
        "deferred_groups": ["c12"],
    }


def test_deferral_cannot_hide_missing_changes_when_capacity_remains():
    source, response = dense_response(MAX_PROPOSALS - 1)
    _, audit = coverage.inspect(SharedItemExtraction(**response), source, staging=False)
    assert audit.status == "needs_review"
    assert {issue["reason"] for issue in audit.issues} == {"unjustified_budget_deferral"}


def test_a_saturated_legacy_response_still_reports_its_unexplained_omission():
    source, response = dense_response()
    response["coverage"]["c12"] = ["conditions"]
    _, audit = coverage.inspect(SharedItemExtraction(**response), source, staging=False)
    assert audit.issues[0]["reason"] == "missing_proposals"
    assert audit.payload()["condition_budget"]["proposed"] == MAX_PROPOSALS
    model = SharedItemExtraction(**response)
    _, sections = coverage.annotate(model, source, read(model, staging=False), staging=False)
    assert any("budget" in text.lower() for text in sections.messages())


def test_dense_turn_review_is_visible_even_when_no_response_section_is_missing():
    source, response = dense_response()
    result = SharedItemExtraction(**response)
    _, sections = coverage.annotate(result, source, read(result, staging=False), staging=False)
    assert not sections.unconfirmed
    assert any("budget" in text.lower() for text in sections.messages())


@pytest.mark.parametrize("staging", [False, True])
def test_wire_schema_accepts_deferral_without_increasing_operation_capacity(staging):
    source, response = dense_response()
    model = SharedItemExtraction if staging else ItemExtraction
    schema = reference_schema.build(model, source, complete=True)
    payload = model.model_validate({**response, "coverage": None}).model_dump()
    payload["coverage"] = response["coverage"]
    validator = Draft202012Validator(schema)
    assert validator.is_valid(payload)
    payload["condition_updates"].append(payload["condition_updates"][0])
    assert not validator.is_valid(payload)
