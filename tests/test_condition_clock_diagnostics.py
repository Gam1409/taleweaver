"""Recording time is not inferred onset, and an empty proposal is not verified absence."""

from copy import deepcopy
from types import SimpleNamespace

from backend.engine.chpm import host_observations
from backend.engine.physical_conditions.ledger import apply, read
from backend.engine.physical_conditions.runtime import finish, stage
from backend.engine.physical_conditions.schema import KEY
from tests.test_physical_conditions import record


def check(states, proposals, *, minute=10, message="m1", narration=None):
    text = (
        narration
        if narration is not None
        else " ".join(row.get("evidence", "") for row in proposals)
    )
    return apply(
        states,
        proposals,
        targets={"RIN"},
        narration=text,
        message_id=message,
        session_id="session",
        minute=minute,
    )


def test_recorded_and_changed_clock_are_preserved_when_later_turn_omits_the_fact():
    states, accepted, errors = check({}, [record()])
    assert accepted and not errors
    identifier = accepted[0]
    row = read(states).conditions[identifier]
    assert row.first_recorded_minute == row.last_changed_minute == 10
    unchanged, _, _ = check(states, [], minute=100, message="m2", narration="Rin checks the clock.")
    assert read(unchanged).conditions[identifier] == row
    treated, _, errors = check(
        unchanged,
        [
            {
                "operation": "treat",
                "condition_id": identifier,
                "evidence": "Rin disinfects the wound.",
            }
        ],
        minute=120,
        message="m3",
    )
    assert not errors
    row = read(treated).conditions[identifier]
    assert row.first_recorded_minute == 10 and row.last_changed_minute == 120


def test_legacy_condition_times_stay_unknown_until_an_actual_update():
    states, accepted, _ = check({}, [record()])
    row = states[KEY]["conditions"][accepted[0]]
    row.pop("first_recorded_minute", None)
    row.pop("last_changed_minute", None)
    assert read(states).conditions[accepted[0]].first_recorded_minute is None
    changed, _, errors = check(
        states,
        [
            {
                "operation": "heal",
                "condition_id": accepted[0],
                "evidence": "The neck wound has completely healed.",
            }
        ],
        minute=75,
        message="m2",
    )
    assert not errors
    row = read(changed).conditions[accepted[0]]
    assert row.first_recorded_minute is None and row.last_changed_minute == 75


def test_rejected_and_repeated_operations_do_not_refresh_the_condition_clock():
    states, accepted, _ = check({}, [record()])
    original = read(states).conditions[accepted[0]]
    repeated, _, _ = check(states, [record()], minute=200)
    assert read(repeated).conditions[accepted[0]] == original
    rejected, _, errors = check(
        states,
        [{"operation": "clean", "condition_id": accepted[0], "evidence": "Rin cleans the wound."}],
        minute=200,
        message="m2",
    )
    assert errors and read(rejected).conditions[accepted[0]] == original
    assert read(rejected).last_check["proposed_count"] == 1


def test_empty_first_extraction_is_visible_but_does_not_claim_known_healthy_state():
    manager = SimpleNamespace(
        state=SimpleNamespace(
            entity_states={}, session_id="session", in_game_time=5, current_scene_id="room"
        )
    )
    stage(manager, [], {"RIN"})
    assert finish(manager, SimpleNamespace(id="reply", content="Rin checks the clock.")) == []
    ledger = read(manager.state.entity_states)
    assert ledger.last_check["proposed_count"] == 0
    assert ledger.last_check["accepted"] == [] and ledger.last_check["rejected"] == []
    before = deepcopy(manager.state.entity_states)
    facts = host_observations.capture(
        manager.state, SimpleNamespace(id="RIN", inventory=[], metadata_json={}), {}
    )
    assert facts.physical_conditions is None
    assert manager.state.entity_states == before


def test_candidate_counts_distinguish_schema_rejection_from_successful_noop():
    states, accepted, errors = check(
        {},
        [
            record(target_id="FOREIGN"),
            record(part="arm"),
            {"operation": "broken", "evidence": "Invalid operation."},
        ],
    )
    assert len(accepted) == 1 and len(errors) == 2
    audit = read(states).last_check
    assert audit["proposed_count"] == 3
    assert audit["proposed_count"] - len(audit["accepted"]) == 2
    states, accepted, errors = check({}, [record()] * 13)
    assert read(states).last_check["proposed_count"] == 13
    assert not accepted and len(errors) == 1
