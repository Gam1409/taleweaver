"""Persistent conditions survive omission; typed operations affect one canonical subject."""

from copy import deepcopy

import pytest

from backend.engine.physical_conditions.ledger import apply, read
from backend.engine.physical_conditions.schema import KEY, ConditionProposal

TARGETS = {"RIN", "MIKI", "COAT_R", "COAT_M"}


def record(**changes):
    return {
        "operation": "record",
        "target_id": "RIN",
        "kind": "injury",
        "part": "neck",
        "detail": "An open neck wound.",
        "visibility": "private",
        "evidence": "Rin has an open neck wound.",
        **changes,
    }


def run(states, proposals, text=None, reply="REPLY1"):
    text = text or " ".join(p.get("evidence", "") for p in proposals if isinstance(p, dict))
    return apply(
        states,
        proposals,
        targets=TARGETS,
        narration=text,
        message_id=reply,
        session_id="S",
        minute=10,
    )


def test_old_sessions_are_empty_and_unmentioned_conditions_persist():
    assert not read({}).conditions
    states, accepted, rejected = run({}, [record()])
    assert len(accepted) == 1 and not rejected
    before = deepcopy(states)
    newer, _, _ = run(states, [], "Rin checks the clock.", reply="REPLY2")
    assert read(newer).conditions == read(before).conditions
    assert states == before


def test_treatment_does_not_heal_and_cleaning_a_wound_is_rejected():
    states, accepted, _ = run({}, [record()])
    identifier = accepted[0]
    updated, _, errors = run(
        states,
        [
            {
                "operation": "treat",
                "condition_id": identifier,
                "evidence": "Rin disinfects the wound.",
            }
        ],
        reply="R2",
    )
    assert not errors and read(updated).conditions[identifier].status == "treated"
    same, _, errors = run(
        updated,
        [{"operation": "clean", "condition_id": identifier, "evidence": "Rin cleans the wound."}],
        reply="R3",
    )
    assert errors and read(same).conditions[identifier].status == "treated"
    healed, _, errors = run(
        updated,
        [
            {
                "operation": "heal",
                "condition_id": identifier,
                "evidence": "The neck wound has completely healed.",
            }
        ],
        reply="R4",
    )
    assert not errors and read(healed).conditions[identifier].status == "resolved"


def test_partial_fluid_removal_keeps_condition_and_outside_does_not_clear_inside():
    states, accepted, _ = run(
        {},
        [
            record(
                kind="fluid",
                part="inside tube",
                detail="Saline remains inside.",
                evidence="Saline remains inside Rin's tube.",
            )
        ],
    )
    identifier = accepted[0]
    changed, _, errors = run(
        states,
        [
            {
                "operation": "reduce",
                "condition_id": identifier,
                "detail": "Some saline remains.",
                "evidence": "Rin drains some saline.",
            }
        ],
        reply="R2",
    )
    assert not errors and read(changed).conditions[identifier].status == "reduced"
    assert read(changed).conditions[identifier].target_id == "RIN"
    outside, _, _ = run(changed, [], "Rin wipes the outside of the tube.", reply="R3")
    assert read(outside).conditions[identifier].status == "reduced"


def test_cleaning_one_coat_does_not_change_another_or_intrinsic_description():
    states, accepted, _ = run(
        {},
        [
            record(
                target_id="COAT_R",
                kind="contamination",
                part="fabric",
                detail="Mud.",
                evidence="Rin's coat is muddy.",
            ),
            record(
                target_id="COAT_M",
                kind="contamination",
                part="fabric",
                detail="Mud.",
                evidence="Miki's coat is muddy.",
            ),
        ],
    )
    changed, _, errors = run(
        states,
        [
            {
                "operation": "clean",
                "condition_id": accepted[0],
                "evidence": "Miki washes Rin's coat.",
            }
        ],
        reply="R2",
    )
    assert not errors
    assert read(changed).conditions[accepted[0]].status == "resolved"
    assert read(changed).conditions[accepted[1]].status == "active"


def test_invalid_operations_do_not_block_independent_valid_proposals():
    proposals = [record(target_id="FOREIGN"), {"operation": "unknown"}, record()]
    states, accepted, errors = run({}, proposals)
    assert len(accepted) == 1 and len(errors) == 2
    assert len(read(states).conditions) == 1
    other, accepted, errors = run(
        states,
        [{"operation": "heal", "condition_id": "FOREIGN", "evidence": "A wound has healed."}],
        reply="R2",
    )
    assert not accepted and errors and read(other).conditions == read(states).conditions


def test_nonliteral_evidence_and_replay_do_not_duplicate_or_clear_conditions():
    states, _, _ = run({}, [record()])
    again, accepted, errors = run(states, [record()])
    assert not accepted and not errors and len(read(again).conditions) == 1
    invalid, accepted, errors = run(
        states,
        [record(part="arm", evidence="A completely invented wound.")],
        "Rin checks the clock.",
        reply="R2",
    )
    assert errors and not accepted and len(read(invalid).conditions) == 1


def test_saved_invalid_state_is_preserved_instead_of_being_replaced():
    bad = {KEY: {"version": 99, "conditions": {}}}
    with pytest.raises(ValueError):
        run(bad, [record()])
    assert bad[KEY]["version"] == 99


def test_known_condition_updates_do_not_repeat_target_ids_in_the_proposal():
    action = ConditionProposal.model_validate(
        {"operation": "treat", "condition_id": "C1", "evidence": "Rin disinfects the wound."}
    )
    assert action.target_id is None
