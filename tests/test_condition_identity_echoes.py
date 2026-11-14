"""Matching immutable echoes do not erase valid updates or redirect their identity."""

from copy import deepcopy

import pytest
from pydantic import ValidationError

from backend.engine.physical_conditions.ledger import apply, read
from backend.engine.physical_conditions.schema import (
    KEY,
    Condition,
    ConditionProposal,
    Ledger,
    Source,
)

TARGETS = {"NPC", "COAT", "BOTTLE"}


def initial():
    source = Source(kind="manual", quote="An initial inspection.")
    rows = (
        ("DIRT", "COAT", "contamination", "surface", "Mud on the coat."),
        ("CUT", "NPC", "injury", "left_hand", "A small open cut."),
        ("CONTENTS", "BOTTLE", "item_state", "contents", "half full"),
        ("PRIVATE", "UNAVAILABLE", "pain", "hand", "A private retained fact."),
    )
    return {
        KEY: Ledger(
            conditions={
                key: Condition(
                    id=key,
                    target_id=target,
                    kind=kind,
                    part=part,
                    detail=detail,
                    origin=source,
                    latest=source,
                    updated_revision=0,
                )
                for key, target, kind, part, detail in rows
            }
        ).model_dump()
    }


def run(proposals, *, states=None, reply="reply"):
    narration = " ".join(row["evidence"] for row in proposals)
    return apply(
        initial() if states is None else states,
        proposals,
        targets=TARGETS,
        item_targets={"COAT", "BOTTLE"},
        narration=narration,
        message_id=reply,
        session_id="session",
        minute=1,
    )


LIVE_ECHOES = (
    (
        {
            "operation": "treat",
            "condition_id": "CUT",
            "target_id": "NPC",
            "evidence": "The cut was disinfected and remains open.",
        },
        "treated",
        "A small open cut.",
    ),
    (
        {
            "operation": "remove",
            "condition_id": "DIRT",
            "target_id": "COAT",
            "kind": "contamination",
            "part": "surface",
            "evidence": "The coat has no remaining dirt.",
        },
        "resolved",
        "Mud on the coat.",
    ),
    (
        {
            "operation": "change",
            "condition_id": "CONTENTS",
            "target_id": "BOTTLE",
            "kind": "item_state",
            "part": "contents",
            "detail": "empty",
            "evidence": "The bottle is empty.",
        },
        "active",
        "empty",
    ),
    (
        {
            "operation": "heal",
            "condition_id": "CUT",
            "target_id": "NPC",
            "kind": "injury",
            "part": "left_hand",
            "evidence": "The hand cut has fully healed.",
        },
        "resolved",
        "A small open cut.",
    ),
)


@pytest.mark.parametrize(("proposal", "status", "detail"), LIVE_ECHOES)
def test_exact_live_identity_echoes_update_only_the_existing_canonical_fact(
    proposal, status, detail
):
    states, raw = initial(), deepcopy(proposal)
    before = deepcopy(states)
    with pytest.raises(ValidationError):
        ConditionProposal.model_validate(raw)
    changed, accepted, errors = run([raw], states=states)
    assert accepted == [proposal["condition_id"]] and not errors
    original, current = read(before), read(changed)
    assert set(current.conditions) == set(original.conditions)
    row = current.conditions[accepted[0]]
    assert row.status == status and row.detail == detail
    assert (row.target_id, row.kind, row.part) == (
        original.conditions[row.id].target_id,
        original.conditions[row.id].kind,
        original.conditions[row.id].part,
    )
    assert all(
        value == original.conditions[key]
        for key, value in current.conditions.items()
        if key != row.id
    )
    assert states == before and raw == proposal
    audit = current.last_check["identity_echoes"]
    assert audit == [
        {
            "proposal": 1,
            "condition_id": row.id,
            "fields": [field for field in ("target_id", "kind", "part") if field in proposal],
        }
    ]


@pytest.mark.parametrize(
    "changes",
    [
        {"target_id": "NPC"},
        {"target_id": "FOREIGN"},
        {"target_id": "coat"},
        {"kind": "injury"},
        {"kind": "item_state"},
        {"kind": "Contamination"},
        {"part": "lining"},
        {"part": "Surface"},
        {"part": None},
        {"target_id": 3},
        {"kind": ["contamination"]},
    ],
)
def test_any_conflicting_echo_rejects_the_whole_update_without_retargeting(changes):
    raw = {**LIVE_ECHOES[1][0], **changes}
    before = initial()
    changed, accepted, errors = run([raw], states=before)
    assert not accepted and errors
    assert read(changed).conditions == read(before).conditions
    assert not read(changed).last_check.get("identity_echoes")


def test_only_existing_whitespace_normalization_is_used_for_echoed_text():
    raw = {
        **LIVE_ECHOES[1][0],
        "condition_id": " DIRT ",
        "target_id": " COAT ",
        "part": " surface ",
    }
    changed, accepted, errors = run([raw])
    assert accepted == ["DIRT"] and not errors
    assert read(changed).conditions["DIRT"].target_id == "COAT"


@pytest.mark.parametrize("identifier", ["UNKNOWN", "PRIVATE"])
def test_unknown_or_out_of_scope_private_conditions_are_not_normalized(identifier):
    raw = {
        "operation": "treat",
        "condition_id": identifier,
        "target_id": "UNAVAILABLE",
        "kind": "pain",
        "part": "hand",
        "evidence": "The hand was treated.",
    }
    before = initial()
    changed, accepted, errors = run([raw], states=before)
    assert not accepted and errors
    assert read(changed).conditions == read(before).conditions
    assert not read(changed).last_check.get("identity_echoes")


def test_matching_echoes_cannot_reopen_a_resolved_condition():
    healed, _, errors = run([LIVE_ECHOES[3][0]])
    assert not errors
    changed, accepted, errors = run([LIVE_ECHOES[0][0]], states=healed, reply="later")
    assert not accepted and errors
    assert read(changed).conditions == read(healed).conditions


def test_matching_echoes_do_not_turn_a_new_record_or_unknown_operation_into_an_update():
    for operation in ("record", "invented"):
        raw = {**LIVE_ECHOES[1][0], "operation": operation, "detail": "A new claim."}
        changed, accepted, errors = run([raw])
        assert not accepted and errors
        assert read(changed).conditions == read(initial()).conditions


def test_unknown_fields_still_fail_instead_of_being_discarded_with_echoes():
    changed, accepted, errors = run([{**LIVE_ECHOES[1][0], "unexpected": "private value"}])
    assert not accepted and errors
    assert "private value" not in " ".join(errors)
    assert read(changed).conditions == read(initial()).conditions


def test_a_conflicting_candidate_does_not_erase_an_independent_matching_update():
    changed, accepted, errors = run(
        [LIVE_ECHOES[1][0], {**LIVE_ECHOES[0][0], "target_id": "BOTTLE"}]
    )
    assert accepted == ["DIRT"] and len(errors) == 1
    assert read(changed).conditions["DIRT"].status == "resolved"
    assert read(changed).conditions["CUT"] == read(initial()).conditions["CUT"]


def test_identity_echo_normalization_does_not_bypass_exact_item_state_evidence():
    raw = {**LIVE_ECHOES[2][0], "detail": "full"}
    changed, accepted, errors = run([raw])
    assert not accepted and errors
    assert read(changed).conditions == read(initial()).conditions
    assert not read(changed).last_check.get("identity_echoes")


def test_identity_echo_normalization_keeps_same_fact_source_order_checks():
    later = LIVE_ECHOES[2][0]
    earlier = {
        **later,
        "detail": "half full",
        "evidence": "The bottle is half full.",
    }
    changed, accepted, errors = apply(
        initial(),
        [later, earlier],
        targets=TARGETS,
        item_targets={"COAT", "BOTTLE"},
        narration="The bottle is half full. The bottle is empty.",
        message_id="reply",
        session_id="session",
        minute=1,
    )
    assert accepted == ["CONTENTS"] and len(errors) == 1
    assert "narrative order" in errors[0]
    assert read(changed).conditions["CONTENTS"].detail == "empty"
    assert len(read(changed).events) == 1


@pytest.mark.parametrize("operation", [None, [], {}])
def test_malformed_operation_is_rejected_without_crashing_or_erasing_valid_updates(operation):
    changed, accepted, errors = run(
        [{**LIVE_ECHOES[1][0], "operation": operation}, LIVE_ECHOES[0][0]]
    )
    assert accepted == ["CUT"] and len(errors) == 1
    assert read(changed).conditions["DIRT"] == read(initial()).conditions["DIRT"]
