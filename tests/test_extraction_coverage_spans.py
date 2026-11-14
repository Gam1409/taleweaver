"""A coalesced final fact can cite its exact adjacent action and confirmation."""

import pytest
from jsonschema import Draft202012Validator

from backend.engine.narrated_items import coverage, evidence, reference_schema
from backend.engine.narrated_items.schema import ItemExtraction, SharedItemExtraction
from backend.engine.physical_conditions import ledger


def catalog(text, *, scope="coverage-span-test"):
    return evidence.Catalog(text, scope=scope)


def update(proof):
    return {
        "operation": "change",
        "condition_id": "CONTENTS",
        "detail": "empty",
        "evidence": proof,
    }


def complete(proof):
    return SharedItemExtraction(
        condition_updates=[update(proof)],
        coverage={"c0": ["conditions"], "c1": ["unchanged"]},
    )


def test_one_contiguous_quote_can_cover_action_and_final_confirmation_without_duplication():
    text = "Alex empties the glass bottle into a drain. The glass bottle is now empty."
    source = catalog(text)
    body, audit = coverage.inspect(complete(text), source, staging=False)
    assert audit.status == "complete" and not audit.issues
    bound = evidence.bind(body, text, catalog=source)
    assert len(bound.condition_updates) == 1
    assert bound.condition_updates[0]["evidence_span"] == {"start": 0, "end": len(text)}


def test_wire_range_is_one_exact_source_and_reconciles_one_existing_fact():
    text = "Alex empties the glass bottle into a drain. The glass bottle is now empty."
    source = catalog(text)
    references = list(source.narration_passages)
    schema = reference_schema.build(ItemExtraction, source, complete=True)
    advertised = schema["$defs"]["NarrationEvidenceReference"]["enum"]
    joined = next(reference for reference in advertised if reference not in references)
    proof = source.resolve(joined, allow_room=False)
    assert proof.quote == text
    assert source.coverage_anchor(proof).reference == references[0]
    candidate = complete(joined).model_dump(exclude={"staging"})
    assert Draft202012Validator(schema).is_valid(candidate)
    body, audit = coverage.inspect(candidate, source, staging=False)
    assert audit.status == "complete"
    bound = evidence.bind(body, text, catalog=source)
    initial, accepted, rejected = ledger.apply(
        {},
        [
            {
                "operation": "record",
                "target_id": "BOTTLE",
                "kind": "item_state",
                "part": "contents",
                "detail": "half full",
                "evidence": "The bottle is half full.",
            }
        ],
        targets={"BOTTLE"},
        item_targets={"BOTTLE"},
        narration="The bottle is half full.",
        message_id="before",
        session_id="session",
        minute=0,
    )
    assert not rejected
    proposals = [dict(bound.condition_updates[0], condition_id=accepted[0])]
    changed, after, errors = ledger.apply(
        initial,
        proposals,
        targets={"BOTTLE"},
        item_targets={"BOTTLE"},
        narration=text,
        message_id="after",
        session_id="session",
        minute=1,
    )
    assert after == accepted and not errors
    saved = ledger.read(changed).conditions[accepted[0]]
    assert saved.detail == "empty" and saved.status == "active"
    assert saved.latest.quote == text


def test_final_sentence_alone_does_not_silently_cover_an_uncited_earlier_event():
    text = "Alex empties the glass bottle into a drain. The glass bottle is now empty."
    source = catalog(text)
    last = list(source.narration_passages)[-1]
    _, audit = coverage.inspect(complete(last), source, staging=False)
    assert audit.status == "needs_review"
    assert audit.issues == (
        {"group": "c0", "reason": "missing_proposals", "domains": ["conditions"]},
    )


@pytest.mark.parametrize("tag", ["historical", "uncertain"])
@pytest.mark.parametrize("reference_format", ["literal", "range"])
def test_coalescing_does_not_bypass_a_non_current_occurrence(tag, reference_format):
    text = 'Alex empties the bottle. Alex recalls, "The bottle was empty yesterday."'
    source = catalog(text)
    refs = list(source.narration_passages)
    proof = text if reference_format == "literal" else refs[0] + ".." + refs[1].rsplit(":", 1)[1]
    candidate = complete(proof).model_copy(update={"coverage": {"c0": ["conditions"], "c1": [tag]}})
    body, audit = coverage.inspect(candidate, source, staging=False)
    assert audit.status == "needs_review" and audit.blocked == 1
    assert body["condition_updates"][0]["evidence"] is None
    assert any(issue["reason"] == "non_current_candidate" for issue in audit.issues)


def test_two_domains_cannot_be_covered_by_one_unrelated_range_candidate():
    text = "Mira hands Alex the scarf. The bottle is now empty."
    source = catalog(text)
    candidate = complete(text).model_copy(
        update={"coverage": {"c0": ["items"], "c1": ["conditions"]}}
    )
    _, audit = coverage.inspect(candidate, source, staging=False)
    assert audit.status == "needs_review"
    assert {"group": "c0", "reason": "missing_proposals", "domains": ["items"]} in audit.issues


def test_one_condition_range_cannot_cover_a_second_subjects_independent_change():
    text = "The coat is clean. The bottle is empty."
    source = catalog(text)
    refs = list(source.narration_passages)
    joined = refs[0] + ".." + refs[1].rsplit(":", 1)[1]
    initial, recorded, errors = ledger.apply(
        {},
        [
            {
                "operation": "record",
                "target_id": "COAT",
                "kind": "contamination",
                "part": "surface",
                "detail": "Mud.",
                "evidence": "The coat is muddy.",
            },
            {
                "operation": "record",
                "target_id": "BOTTLE",
                "kind": "item_state",
                "part": "contents",
                "detail": "half full",
                "evidence": "The bottle is half full.",
            },
        ],
        targets={"COAT", "BOTTLE"},
        item_targets={"COAT", "BOTTLE"},
        narration="The coat is muddy. The bottle is half full.",
        message_id="before",
        session_id="session",
        minute=0,
    )
    assert len(recorded) == 2 and not errors
    candidate = SharedItemExtraction(
        condition_updates=[{"operation": "clean", "condition_id": recorded[0], "evidence": joined}],
        coverage={"c0": ["conditions"], "c1": ["conditions"]},
    )
    body, audit = coverage.inspect(candidate, source, staging=False)
    assert audit.status == "needs_review"
    assert audit.issues == (
        {"group": "c1", "reason": "missing_proposals", "domains": ["conditions"]},
    )
    bound = evidence.bind(body, text, catalog=source)
    changed, accepted, rejected = ledger.apply(
        initial,
        bound.condition_updates,
        targets={"COAT", "BOTTLE"},
        item_targets={"COAT", "BOTTLE"},
        narration=text,
        message_id="after",
        session_id="session",
        minute=1,
    )
    assert accepted == [recorded[0]] and not rejected
    assert ledger.read(changed).conditions[recorded[1]].detail == "half full"


def test_a_second_change_in_the_same_subjects_other_dimension_needs_its_own_proposal():
    text = "The bottle is clean. The bottle is empty."
    source = catalog(text)
    candidate = complete(text).model_copy(
        update={"coverage": {"c0": ["conditions"], "c1": ["conditions"]}}
    )
    _, audit = coverage.inspect(candidate, source, staging=False)
    assert audit.status == "needs_review"
    assert audit.issues == (
        {"group": "c1", "reason": "missing_proposals", "domains": ["conditions"]},
    )


def test_one_wide_literal_cannot_claim_arbitrary_fragments_as_covered():
    text = "The coat is torn. Her hand remains dirty. The bottle is empty."
    source = catalog(text)
    candidate = SharedItemExtraction(
        condition_updates=[update(text)],
        coverage={"c0": ["conditions"], "c1": ["conditions"], "c2": ["conditions"]},
    )
    _, audit = coverage.inspect(candidate, source, staging=False)
    assert audit.status == "needs_review"
    assert {row["group"] for row in audit.issues} == {"c0", "c1", "c2"}


def test_ranges_are_adjacent_bounded_and_do_not_change_original_groups():
    text = "First original fact. Second original fact. Third original fact."
    source = catalog(text)
    original = list(source.narration_passages)
    expanded = source.references(include_ranges=True)
    assert len(expanded) == 2 * len(original) - 1
    assert source.references() == original
    assert [ref for group in coverage.groups(source).values() for ref in group] == original
    ranges = [source.resolve(ref, allow_room=False) for ref in expanded if ref not in original]
    assert all(len(row.quote) <= 600 and row.quote != text for row in ranges)
    with pytest.raises(ValueError, match="Unknown or stale"):
        source.resolve(original[0] + "..p2", allow_room=False)


def test_ranges_over_the_common_condition_quote_limit_are_not_advertised():
    text = "A" * 400 + ". " + "B" * 400 + "."
    source = catalog(text)
    assert len(source.narration_passages) == 2
    assert source.references(include_ranges=True) == source.references()


@pytest.mark.parametrize("length,offered", [(600, True), (601, False)])
def test_joined_quote_boundary_agrees_with_condition_proposal_validation(length, offered):
    from backend.engine.physical_conditions.schema import ConditionProposal

    text = "A" * 298 + ". " + "B" * (length - 301) + "."
    assert len(text) == length
    source = catalog(text)
    assert len(source.narration_passages) == 2
    extra = set(source.references(include_ranges=True)) - set(source.references())
    assert bool(extra) is offered
    if offered:
        selected = source.resolve(extra.pop(), allow_room=False)
        assert ConditionProposal.model_validate(update(selected.quote)).evidence == text


def test_range_reference_never_reuses_other_turn_or_room_text():
    text = "The bottle is emptied. The bottle is empty."
    source = catalog(text)
    expanded = source.references(include_ranges=True)
    joined = next(ref for ref in expanded if ref not in source.narration_passages)
    other = catalog(text, scope="another-turn")
    with pytest.raises(ValueError, match="Unknown or stale"):
        other.resolve(joined, allow_room=False)
    room = evidence.Catalog("Mira waits.", text, scope="room-only")
    assert all(ref.startswith("narration:") for ref in room.references(include_ranges=True))


def test_joined_proof_does_not_authorize_a_detail_missing_from_its_actual_text():
    text = "Alex empties the glass bottle into a drain. The glass bottle is now empty."
    source = catalog(text)
    refs = list(source.narration_passages)
    joined = refs[0] + ".." + refs[1].rsplit(":", 1)[1]
    candidate = SharedItemExtraction(
        condition_updates=[
            {
                "operation": "record",
                "target_id": "BOTTLE",
                "kind": "item_state",
                "part": "contents",
                "detail": "full",
                "evidence": joined,
            }
        ],
        coverage={"c0": ["conditions"], "c1": ["unchanged"]},
    )
    body, audit = coverage.inspect(candidate, source, staging=False)
    assert audit.status == "complete"
    bound = evidence.bind(body, text, catalog=source)
    changed, accepted, rejected = ledger.apply(
        {},
        bound.condition_updates,
        targets={"BOTTLE"},
        item_targets={"BOTTLE"},
        narration=text,
        message_id="reply",
        session_id="session",
        minute=1,
    )
    assert not accepted and rejected and not ledger.read(changed).conditions


def test_noncontiguous_literal_proof_does_not_gain_coverage_or_bind_as_a_source():
    text = "Alex empties the bottle. Mira folds a map. The bottle is empty."
    source = catalog(text)
    stitched = "Alex empties the bottle. The bottle is empty."
    with pytest.raises(ValueError, match="Ambiguous or missing"):
        source.literal(stitched, allow_room=False)
    _, audit = coverage.inspect(
        SharedItemExtraction(
            condition_updates=[update(stitched)],
            coverage={"c0": ["conditions"], "c1": ["unchanged"], "c2": ["unchanged"]},
        ),
        source,
        staging=False,
    )
    assert audit.status == "needs_review"
