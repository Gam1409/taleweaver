"""Coverage corrections add supported proposals without rewriting earlier decisions."""

from copy import deepcopy

import pytest
from jsonschema import Draft202012Validator

from backend.engine.narrated_items import coverage, evidence, extraction_repair, independent_state
from backend.engine.narrated_items.apply import apply_actions
from backend.engine.narrated_items.schema import SharedItemExtraction
from backend.engine.physical_conditions import ledger
from tests.test_condition_identity_echoes import initial
from tests.test_narrated_items import action, fixtures


def example():
    catalog = evidence.Catalog("The coat is clean. The bottle is empty.", scope="repair-test")
    refs = list(catalog.narration_passages)
    result = SharedItemExtraction(
        coverage={"c0": ["conditions"], "c1": ["conditions"]},
        condition_updates=[{"operation": "clean", "condition_id": "C_DIRT", "evidence": refs[0]}],
        actions=[],
        scene_updates=[],
        final_frame_actions=[],
        movements=[],
    )
    return catalog, result, refs


def test_missing_independent_fact_requires_its_own_anchored_proposal():
    catalog, result, refs = example()
    before = result.model_dump()
    targets = extraction_repair.targets(result, catalog, staging=False)
    assert targets == {"c1": {"conditions"}}
    patch = extraction_repair.Additions(
        actions=[],
        condition_updates=[
            {
                "operation": "change",
                "condition_id": "C_CONTENTS",
                "detail": "empty",
                "evidence": refs[1],
            }
        ],
        classification_review=[],
    )
    merged, audit = extraction_repair.merge(result, patch, targets, catalog, staging=False)
    assert audit["status"] == "repaired"
    assert merged.condition_updates[0] == result.condition_updates[0]
    assert merged.condition_updates[1]["condition_id"] == "C_CONTENTS"
    assert coverage.inspect(merged, catalog, staging=False)[1].status == "complete"
    assert result.model_dump() == before


def test_corrected_omission_changes_actual_existing_record_without_erasing_other_facts():
    catalog, result, refs = example()
    result.condition_updates[0]["condition_id"] = "DIRT"
    patch = extraction_repair.Additions(
        condition_updates=[
            {
                "operation": "change",
                "condition_id": "CONTENTS",
                "detail": "empty",
                "evidence": refs[1],
            }
        ]
    )
    merged, _ = extraction_repair.merge(
        result, patch, {"c1": {"conditions"}}, catalog, staging=False
    )
    body, audit = coverage.inspect(merged, catalog, staging=False)
    bound = evidence.bind(body, catalog.narration, catalog=catalog)
    changed, accepted, rejected = ledger.apply(
        initial(),
        bound.condition_updates,
        targets={"COAT", "BOTTLE", "NPC"},
        item_targets={"COAT", "BOTTLE"},
        narration=catalog.narration,
        message_id="AFTER",
        session_id="TEST",
        minute=1,
    )
    saved = ledger.read(changed).conditions
    assert audit.status == "complete" and not rejected and accepted == ["DIRT", "CONTENTS"]
    assert saved["DIRT"].status == "resolved" and saved["CONTENTS"].detail == "empty"
    assert saved["CUT"].status == "active" and saved["PRIVATE"].target_id == "UNAVAILABLE"


def test_uncertain_classification_cannot_also_submit_a_fact_for_the_same_missing_domain():
    catalog, result, refs = example()
    patch = extraction_repair.Additions(
        condition_updates=[
            {
                "operation": "change",
                "condition_id": "CONTENTS",
                "detail": "empty",
                "evidence": refs[1],
            }
        ],
        classification_review=[{"group": "c1", "domain": "conditions", "reason": "uncertain"}],
    )
    merged, audit = extraction_repair.merge(
        result, patch, {"c1": {"conditions"}}, catalog, staging=False
    )
    assert merged is result and audit["status"] == "invalid_additions"


def test_classification_note_never_clears_an_unapplied_fact():
    catalog, result, _ = example()
    patch = extraction_repair.Additions(
        actions=[],
        condition_updates=[],
        classification_review=[
            {"group": "c1", "domain": "conditions", "reason": "no_supported_change"}
        ],
    )
    merged, audit = extraction_repair.merge(
        result,
        patch,
        extraction_repair.targets(result, catalog, staging=False),
        catalog,
        staging=False,
    )
    assert merged is result and audit["status"] == "classification_review"
    assert coverage.inspect(merged, catalog, staging=False)[1].status == "needs_review"


@pytest.mark.parametrize(
    "review",
    [None, "no_supported_change", "different_domain", "repeated_confirmation", "uncertain"],
)
def test_known_transfer_and_review_for_the_same_pair_remain_mutually_exclusive(review):
    source = evidence.Catalog("Anna hands the shirt to the hero.", scope="transfer-review")
    reference = next(iter(source.narration_passages))
    original = SharedItemExtraction(
        coverage={"c0": ["items"]},
        actions=[],
        condition_updates=[],
        scene_updates=[],
        final_frame_actions=[],
        movements=[],
    )
    notes = [{"group": "c0", "domain": "items", "reason": review}] if review else []
    patch = extraction_repair.Additions(
        actions=[action(evidence=reference).model_dump()], classification_review=notes
    )
    merged, audit = extraction_repair.merge(
        original, patch, {"c0": {"items"}}, source, staging=False
    )
    body, status = coverage.inspect(merged, source, staging=False)
    bound = evidence.bind(body, source.narration, catalog=source)
    actors, snapshot = fixtures()
    extracted, failures, _, indices = independent_state.unpack(bound, actors)
    changed, accepted, errors = apply_actions(
        extracted,
        actors,
        snapshot,
        source.narration,
        detailed=True,
        session_id="TEST",
        message_id="TURN",
        source_indices=indices,
    )
    assert not failures and not errors and original.actions == []
    if review:
        assert merged is original and audit["status"] == "invalid_additions"
        assert status.status == "needs_review" and not accepted
        assert changed["__player__"]["inventory"] == []
        return
    assert audit["status"] == "repaired" and status.status == "complete"
    assert [row["item"]["id"] for row in accepted] == ["SHIRT"]
    assert [row["id"] for row in changed["__player__"]["inventory"]] == ["SHIRT"]
    assert changed["NPC"]["inventory"] == []


def test_review_of_another_pair_does_not_discard_a_supported_addition():
    source, original, refs = example()
    original.coverage["c0"] = ["items", "conditions"]
    patch = extraction_repair.Additions(
        condition_updates=[
            {
                "operation": "change",
                "condition_id": "C_CONTENTS",
                "detail": "empty",
                "evidence": refs[1],
            }
        ],
        classification_review=[{"group": "c0", "domain": "items", "reason": "different_domain"}],
    )
    merged, audit = extraction_repair.merge(
        original, patch, {"c0": {"items"}, "c1": {"conditions"}}, source, staging=False
    )
    assert merged.condition_updates[-1]["condition_id"] == "C_CONTENTS"
    assert audit["status"] == "unresolved" and audit["classification_review"][0]["group"] == "c0"
    issues = coverage.inspect(merged, source, staging=False)[1].issues
    assert issues == ({"group": "c0", "reason": "missing_proposals", "domains": ["items"]},)


@pytest.mark.parametrize("proof", ["wrong", "range", "already_covered"])
def test_invalid_or_incidental_proof_cannot_repair_the_second_occurrence(proof):
    catalog, result, refs = example()
    value = {
        "wrong": "narration:foreign:p1",
        "range": refs[0] + "..p1",
        "already_covered": refs[0],
    }[proof]
    patch = extraction_repair.Additions(
        condition_updates=[
            {
                "operation": "change",
                "condition_id": "C_CONTENTS",
                "detail": "empty",
                "evidence": value,
            }
        ]
    )
    merged, audit = extraction_repair.merge(
        result, patch, {"c1": {"conditions"}}, catalog, staging=False
    )
    assert merged is result and audit["status"] == "invalid_additions"


@pytest.mark.parametrize("change", ["same_condition", "same_item", "extra_scene", "too_many"])
def test_correction_cannot_replace_an_existing_chain_or_expand_scope(change):
    catalog, result, refs = example()
    if change == "same_condition":
        raw = {
            "condition_updates": [
                {"operation": "remove", "condition_id": "C_DIRT", "evidence": refs[1]}
            ]
        }
    elif change == "same_item":
        row = {
            "item_id": "COAT",
            "source_owner": "MIRA",
            "destination_owner": "MIRA",
            "disposition": "worn",
            "basis": "completed",
            "evidence": refs[0],
        }
        result.actions = [row]
        raw = {"actions": [{**row, "evidence": refs[1]}]}
    elif change == "extra_scene":
        with pytest.raises(ValueError):
            extraction_repair.Additions.model_validate({"scene_updates": []})
        return
    else:
        raw = {
            "condition_updates": [
                {"operation": "remove", "condition_id": f"C{index}", "evidence": refs[1]}
                for index in range(12)
            ]
        }
    patch = extraction_repair.Additions.model_validate(raw)
    merged, audit = extraction_repair.merge(
        result, patch, {"c1": {"items", "conditions"}}, catalog, staging=False
    )
    assert merged is result and audit["status"] == "invalid_additions"


@pytest.mark.parametrize("label", ["uncertain", "conditions_deferred", "invalid"])
def test_ambiguous_or_budget_deferred_answers_do_not_admit_another_request(label):
    catalog, result, _ = example()
    result.coverage["c1"] = [label]
    assert extraction_repair.targets(result, catalog, staging=False) == {}


def test_patch_wire_has_no_coverage_reclassification_and_keeps_source_enums():
    catalog, _, refs = example()
    schema = extraction_repair.schema(catalog)
    validator = Draft202012Validator(schema)
    raw = {"actions": [], "condition_updates": [], "classification_review": []}
    assert validator.is_valid(raw)
    assert not validator.is_valid({**raw, "coverage": {"c1": ["unchanged"]}})
    raw["condition_updates"] = [
        {
            "operation": "change",
            "condition_id": "C_CONTENTS",
            "detail": "empty",
            "evidence": refs[1],
        }
    ]
    assert validator.is_valid(raw)
    wrong = deepcopy(raw)
    wrong["condition_updates"][0]["evidence"] = "narration:foreign:p1"
    assert not validator.is_valid(wrong)
