"""Automatic extraction reuses an unambiguous physical fact without weakening its ledger."""

from copy import deepcopy
from types import SimpleNamespace

import pytest

from backend.engine.physical_conditions.ledger import apply, read
from backend.engine.physical_conditions.runtime import finish, stage
from backend.engine.physical_conditions.schema import KEY
from tests.test_physical_conditions import record, run


def commit(states, proposals, text, *, minute=40):
    manager = SimpleNamespace(
        state=SimpleNamespace(entity_states=deepcopy(states), session_id="S", in_game_time=minute)
    )
    stage(manager, proposals, {"RIN", "MIKI"})
    warnings = finish(manager, SimpleNamespace(id="NEXT", content=text))
    return manager.state.entity_states, warnings


def test_repeated_record_updates_the_same_condition_and_preserves_treatment_and_origin():
    states, identifiers, _ = run({}, [record()])
    identifier = identifiers[0]
    states, _, _ = run(
        states,
        [{"operation": "treat", "condition_id": identifier, "evidence": "Rin dresses the wound."}],
        reply="TREATED",
    )
    original = read(states).conditions[identifier]
    quote = "Rin's neck wound is still painful under the dressing."
    proposal = record(part="NECK", detail="Painful dressed neck wound.", evidence=quote)

    updated, warnings = commit(states, [proposal], quote)

    assert not warnings
    ledger = read(updated)
    assert set(ledger.conditions) == {identifier}
    condition = ledger.conditions[identifier]
    assert condition.status == "treated" and condition.part == "neck"
    assert condition.origin == original.origin
    assert condition.first_recorded_minute == 10 and condition.last_changed_minute == 40
    assert condition.detail == proposal["detail"] and condition.latest.message_id == "NEXT"
    assert ledger.events[-1].operation == "change"
    assert ledger.last_check["reference_bindings"] == [{"proposal": 1, "condition_id": identifier}]


def test_an_unchanged_observation_refreshes_its_source_without_restarting_its_clock():
    states, identifiers, _ = run({}, [record()])
    updated, warnings = commit(states, [record()], record()["evidence"])
    assert not warnings
    condition = read(updated).conditions[identifiers[0]]
    assert condition.last_changed_minute == condition.first_recorded_minute == 10
    assert condition.latest.message_id == "NEXT"


@pytest.mark.parametrize("field,value", [("target_id", "MIKI"), ("kind", "pain"), ("part", "arm")])
def test_distinct_subject_kind_or_part_creates_a_distinct_condition(field, value):
    states, _, _ = run({}, [record()])
    quote = "Miki has a painful arm; Rin's neck remains wounded."
    updated, warnings = commit(states, [record(**{field: value}, evidence=quote)], quote)
    assert not warnings and len(read(updated).conditions) == 2


def test_resolved_conditions_are_not_reopened_by_binding():
    states, identifiers, _ = run({}, [record()])
    states, _, _ = run(
        states,
        [
            {
                "operation": "heal",
                "condition_id": identifiers[0],
                "evidence": "The wound has healed.",
            }
        ],
        reply="HEALED",
    )
    updated, warnings = commit(states, [record()], record()["evidence"])
    assert not warnings and len(read(updated).conditions) == 2
    assert read(updated).conditions[identifiers[0]].status == "resolved"


def test_ambiguous_legacy_duplicates_remain_rejected_and_preserved():
    states, identifiers, _ = run({}, [record()])
    duplicate = deepcopy(states[KEY]["conditions"][identifiers[0]])
    duplicate["id"] = "LEGACY_DUPLICATE"
    states[KEY]["conditions"][duplicate["id"]] = duplicate
    updated, warnings = commit(states, [record()], record()["evidence"])
    assert warnings
    assert read(updated).conditions == read(states).conditions


def test_binding_keeps_exact_source_and_independent_proposal_checks():
    states, _, _ = run({}, [record()])
    quote = "Miki has a sore arm."
    updated, warnings = commit(
        states, [record(), record(target_id="MIKI", part="arm", evidence=quote)], quote
    )
    assert warnings
    assert len(read(updated).conditions) == 2
    assert len(read(updated).last_check["rejected"]) == 1
    assert "exact quote" in read(updated).last_check["rejected"][0]
    assert (
        next(
            row for row in read(updated).conditions.values() if row.target_id == "RIN"
        ).latest.message_id
        == "REPLY1"
    )


def test_manual_record_operation_remains_strict_about_existing_conditions():
    states, _, _ = run({}, [record()])
    updated, accepted, errors = apply(
        states,
        [record()],
        targets={"RIN"},
        narration=record()["evidence"],
        message_id="MANUAL",
        session_id="S",
        minute=40,
        manual=True,
    )
    assert errors and not accepted
    assert read(updated).conditions == read(states).conditions


def test_replaying_the_same_saved_message_does_not_add_another_update():
    states, _, _ = run({}, [record()])
    updated, warnings = commit(states, [record()], record()["evidence"])
    assert not warnings
    replayed, warnings = commit(updated, [record()], record()["evidence"], minute=90)
    assert not warnings and replayed == updated


def test_unknown_subject_cannot_rebind_an_existing_fact_outside_the_available_scope():
    states, _, _ = run({}, [record(target_id="COAT_R")])
    updated, warnings = commit(states, [record(target_id="COAT_R")], record()["evidence"])
    assert warnings and read(updated).conditions == read(states).conditions
