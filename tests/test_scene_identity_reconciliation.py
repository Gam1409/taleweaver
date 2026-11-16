"""Repeated scene observations retain canonical identities and source boundaries."""

from copy import deepcopy

import pytest

from backend.engine.scene_continuity.ledger import read
from backend.engine.scene_continuity.presentation import project
from tests.test_scene_continuity import apply_to, message, state, update


def test_repeated_record_updates_one_existing_fact_and_preserves_its_origin():
    saved, _ = apply_to()
    initial = next(iter(read(saved).records.values()))
    text = "The kettle is now boiling strongly."
    changed, errors = apply_to(
        saved,
        [update(detail="Kettle boils strongly", evidence=text, visual_detail=text)],
        minute=11,
        reply=message("later", text),
    )
    assert not errors
    ledger = read(changed)
    assert len(ledger.records) == 1
    row = ledger.records[initial.id]
    assert row.detail == "Kettle boils strongly" and row.origin == initial.origin
    assert row.latest.source_id == "later" and row.latest.quote == text
    assert ledger.last_check["reference_bindings"] == [{"proposal": 1, "record_id": initial.id}]


def test_extraction_context_exposes_identity_and_audience_metadata_only_to_its_caller():
    saved, _ = apply_to(updates=[update(visibility="private", observers=["LINA"])])
    fact = project(state(saved), include_private=True)["facts"][0]
    assert fact["key"] == "boiling"
    assert fact["visibility"] == "private" and fact["observers"] == ["LINA"]
    assert not project(state(saved), actor_id="STRANGER")["facts"]
    public = project(state(saved), actor_id="LINA")["facts"][0]
    assert "observers" not in public and "key" not in public


@pytest.mark.parametrize("mutation", ["source", "subject", "key", "kind", "time", "ended"])
def test_identity_binding_does_not_relax_independent_validation(mutation):
    saved, _ = apply_to()
    previous = deepcopy(read(saved).records)
    text = "The kettle is now boiling strongly."
    proposal = update(evidence=text)
    minute = 11
    if mutation == "source":
        proposal["evidence"] = "A paraphrased source."
    elif mutation == "subject":
        proposal["subject_id"] = "ABSENT"
    elif mutation == "key":
        proposal["key"] = ""
    elif mutation == "kind":
        proposal["kind"] = "environment"
    elif mutation == "time":
        minute = 9
    else:
        identifier = next(iter(previous))
        saved, _ = apply_to(
            saved,
            [{"operation": "end", "record_id": identifier, "evidence": text}],
            reply=message("ended", text),
        )
        previous = deepcopy(read(saved).records)
    changed, errors = apply_to(saved, [proposal], minute=minute, reply=message("bad", text))
    assert errors and read(changed).records == previous


def test_rebound_observations_keep_current_source_order():
    saved, _ = apply_to()
    earlier = "The kettle boils gently."
    later = "The kettle boils strongly."
    changed, errors = apply_to(
        saved,
        [update(detail=later, evidence=later), update(detail=earlier, evidence=earlier)],
        reply=message("ordered", earlier + " " + later),
    )
    assert len(errors) == 1
    assert next(iter(read(changed).records.values())).detail == later


def test_sparse_rebound_record_preserves_existing_private_observers_and_deadline():
    saved, _ = apply_to(
        updates=[update(visibility="private", observers=["LINA"], review_after_minutes=5)]
    )
    text = "The kettle boils more strongly."
    changed, errors = apply_to(
        saved,
        [
            {
                "operation": "record",
                "key": "boiling",
                "kind": "process",
                "subject_id": "KETTLE",
                "detail": text,
                "evidence": text,
            }
        ],
        minute=11,
        reply=message("sparse", text),
    )
    assert not errors
    row = next(iter(read(changed).records.values()))
    assert row.visibility == "private" and row.observers == ["LINA"]
    assert row.review_at_minute == 15


def test_repeated_authored_environment_has_no_artificial_event_order():
    from tests.test_scene_continuity import ROOM

    proposal = update(
        key="room",
        kind="environment",
        subject_id="LAB",
        source="scene_description",
        detail="Cobalt mosaic walls",
        evidence="Cobalt mosaic walls and warm brass ceiling lamps.",
    )
    saved, errors = apply_to(updates=[proposal])
    assert not errors
    first = next(iter(read(saved).records.values()))
    changed, errors = apply_to(saved, [proposal], reply=message("another-reply", ROOM))
    assert not errors and len(read(changed).records) == 1
    assert read(changed).records[first.id].origin == first.origin


def test_ambiguous_legacy_scene_identity_is_not_guessed():
    from backend.engine.scene_continuity.schema import KEY

    saved, _ = apply_to()
    ledger = read(saved)
    first = next(iter(ledger.records.values()))
    ledger.records["legacy-duplicate"] = first.model_copy(update={"id": "legacy-duplicate"})
    saved = {KEY: ledger.model_dump()}
    text = "The kettle now boils strongly."
    changed, errors = apply_to(saved, [update(evidence=text)], reply=message("ambiguous", text))
    assert errors and read(changed).records == ledger.records
    assert not read(changed).last_check.get("reference_bindings")


def test_explicit_final_ending_keeps_the_existing_same_passage_contract():
    saved, _ = apply_to()
    first = next(iter(read(saved).records.values()))
    text = "The kettle boils briefly and then stops."
    changed, errors = apply_to(
        saved,
        [
            update(detail="Kettle boils briefly", evidence=text),
            {
                "operation": "end",
                "record_id": first.id,
                "evidence": text,
                "visibility": "public",
            },
        ],
        reply=message("completed", text),
    )
    assert not errors
    assert read(changed).records[first.id].status == "ended"
    assert read(changed).records[first.id].origin == first.origin
