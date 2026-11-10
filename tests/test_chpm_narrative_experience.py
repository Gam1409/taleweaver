"""Narrator reasons remain bounded, observer-local and explicitly historical when stale."""

from copy import deepcopy

import pytest

from backend.engine.chpm import continuation, experience, narrative_context
from backend.engine.chpm.core.contracts import Advance, Event
from backend.engine.chpm.core.reducer import apply
from backend.engine.chpm.host_state import Mind
from tests.test_chpm_appraisal import heard
from tests.test_chpm_experience import accept, proposed
from tests.test_chpm_host_state import mind


def project(value, cursors=None):
    return narrative_context.experience_reasons(
        value, continuation.experience_view(value, cursors or {})
    )


def test_exact_saved_reasons_are_visible_without_mutating_mind_or_technical_view():
    value, _ = accept(heard(text="You must obey"), [proposed()])
    technical = experience.view(value)
    original = deepcopy(technical)
    saved = value.model_dump_json()
    projected = narrative_context.experience_reasons(value, technical)
    assert projected["states"][0]["last_assessed_reason"] == "Pressure may threaten autonomy"
    assert projected["states"][0]["status"] == "recent_appraisal"
    assert projected["omitted_reasons"] == 0
    assert technical == original
    assert value.model_dump_json() == saved
    assert "last_assessed_reason" not in experience.view(value)["states"][0]
    assert project(mind())["states"] == []  # No appraisals does not mean calm.


@pytest.mark.parametrize("gap", [False, True])
def test_old_reasons_do_not_become_fresh_feelings_after_time_or_unreviewed_turns(gap):
    value, _ = accept(heard(text="You must obey"), [proposed()])
    if not gap:
        snapshot = apply(
            value.snapshot,
            Event(
                scope=value.genesis.scope,
                event_id="later",
                sequence=3,
                sim_minute=100,
                payload=Advance(),
            ),
            expected_revision=2,
        ).snapshot
        value = Mind(genesis=value.genesis, snapshot=snapshot, sources=value.sources)
    cursors = {value.genesis.scope.observer_id: 2} if gap else {}
    state = project(value, cursors)["states"][0]
    assert state["status"] == "historical_current_unknown"
    assert state["last_assessed_level"] == "moderate"
    assert state["last_assessed_reason"] == "Pressure may threaten autonomy"


@pytest.mark.parametrize("reason", ["A tentative reason", '"\\' * 90])
def test_reason_count_and_total_extra_serialized_characters_are_bounded(reason):
    value, _ = accept(
        heard(text="You must obey"),
        [
            proposed(explanation=reason),
            proposed(
                channel="need_frustration", dimension="autonomy", about_id=None, explanation=reason
            ),
            proposed(
                channel="need_frustration",
                dimension="relatedness",
                about_id=None,
                explanation=reason,
            ),
        ],
    )
    result = project(value)
    rows = [row for row in result["states"] if "last_assessed_reason" in row]
    assert 1 <= len(rows) <= narrative_context.EXPERIENCE_REASON_LIMIT
    assert all(row["last_assessed_reason"] == reason for row in rows)
    assert result["omitted_reasons"] == 3 - len(rows)
    assert any(row["channel"] == "affect" for row in rows)
    assert narrative_context._size(result) - narrative_context._size(experience.view(value)) <= (
        narrative_context.EXPERIENCE_REASON_EXTRA_CHARS
    )


def test_canonical_archived_experience_keeps_its_reason():
    value, _ = accept(heard(text="You must obey"), [proposed()])
    for index in range(260):
        value = heard(value, message=f"later-{index}", text="The conversation continues.")
    assert value.snapshot.archive
    assert not any(event.payload.kind == "experience" for event in value.snapshot.journal)
    assert project(value)["states"][0]["last_assessed_reason"] == ("Pressure may threaten autonomy")


def test_projection_does_not_resolve_another_observers_record():
    owner, _ = accept(heard(text="You must obey"), [proposed()])
    unrelated = mind(actor="other")
    result = narrative_context.experience_reasons(unrelated, experience.view(owner))
    assert "last_assessed_reason" not in result["states"][0]
