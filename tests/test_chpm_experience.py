"""Temporary experience is sourced, reversible and never a replacement personality."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.engine.chpm import appraisal_context, cognition, experience, lifecycle, motivation
from backend.engine.chpm.appraisal_contracts import FeltExperience
from backend.engine.chpm.core.contracts import Advance, Event
from backend.engine.chpm.core.reducer import apply
from backend.engine.chpm.core.replay import restore
from backend.engine.chpm.host_state import Mind, before_messages
from backend.engine.chpm.schema import KernelState, Settings, Usage
from backend.engine.chpm.state import KEY
from tests.test_chpm_appraisal import heard
from tests.test_chpm_kernel import observation


def proposed(**changes):
    return FeltExperience.model_validate(
        {
            "channel": "affect",
            "dimension": "fear",
            "about_id": "@player",
            "level": "moderate",
            "citations": [{"source_id": "e1", "quote": "You must obey"}],
            "personal_motive_ids": ["character"],
            "explanation": "Pressure may threaten autonomy",
            "alternatives": ["May instead feel anger"],
            "unknowns": ["Current physical threat"],
            **changes,
        }
    )


def accept(value, proposals, message="m1"):
    window = appraisal_context.build(value)
    return experience.accept(
        value, proposals, window, motivation.build(value, [], window), message_id=message
    )


def test_mixed_affect_and_need_frustration_preserve_identity_and_relationships():
    value = heard(text="You must obey")
    changed, ids = accept(
        value,
        [proposed(), proposed(channel="need_frustration", dimension="autonomy", about_id=None)],
    )
    assert len(ids) == len(changed.snapshot.experiences) == 2
    assert changed.genesis == value.genesis
    assert changed.snapshot.beliefs == value.snapshot.beliefs
    assert experience.view(changed)["states"][0]["status"] == "recent_appraisal"
    assert (
        restore(changed.snapshot.model_dump(), expected_genesis=value.genesis) == changed.snapshot
    )
    assert Mind.model_validate_json(changed.model_dump_json()) == changed
    assert accept(changed, [proposed()])[0] == changed  # exact retry is idempotent
    assert before_messages(changed, {"m1"}).snapshot.experiences == ()


def test_time_makes_current_intensity_unknown_without_healing_or_trait_change():
    value, _ = accept(heard(text="You must obey"), [proposed()])
    advanced = apply(
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
    later = Mind(genesis=value.genesis, snapshot=advanced, sources=value.sources)
    state = experience.view(later)["states"][0]
    assert state["status"] == "historical_current_unknown"
    assert state["last_assessed_level"] == "moderate"
    assert later.snapshot.experiences == value.snapshot.experiences
    assert later.genesis == value.genesis


@pytest.mark.parametrize(
    "changes",
    [
        {"dimension": "trust"},
        {"dimension": "personality"},
        {"channel": "need_satisfaction"},
        {"consent": True},
        {"level": "unknown"},
        {"diagnosis": "PTSD"},
    ],
)
def test_unsupported_constructs_and_patches_are_not_experience(changes):
    with pytest.raises(ValueError):
        proposed(**changes)


@pytest.mark.parametrize(
    "changes",
    [
        {"personal_motive_ids": ["report-e1"]},
        {"personal_motive_ids": ["hidden-value"]},
        {"about_id": "unknown-person"},
        {"citations": [{"source_id": "e1", "quote": "Invented quote"}]},
    ],
)
def test_invalid_grounding_rejects_entire_batch_without_mutation(changes):
    value = heard(text="You must obey")
    before = value.model_dump_json()
    with pytest.raises(ValueError):
        accept(
            value,
            [
                proposed(),
                proposed(
                    channel="need_frustration",
                    dimension="autonomy",
                    about_id=None,
                    **{k: v for k, v in changes.items() if k != "about_id"},
                ),
            ]
            if "about_id" not in changes
            else [proposed(**changes)],
        )
    assert value.model_dump_json() == before


def test_recall_alone_cannot_refresh_and_fork_rebinds_experience_citations():
    original = heard(text="You must obey")
    changed, _ = accept(original, [proposed()])
    with pytest.raises(ValueError, match="current observed trigger"):
        accept(original, [proposed()], "different-turn")
    # Same roots under a new record ID are not a new emotional trigger.
    altered = proposed(level="high")
    with pytest.raises(ValueError, match="Repeated grounds"):
        accept(changed, [altered])
    copied = lifecycle.fork(
        {KEY: KernelState(minds={"npc": changed}).model_dump()}, {"m1": "copy"}, "copy-session"
    )
    forked = KernelState.model_validate(copied[KEY]).minds["npc"]
    assert forked.snapshot.experiences[0].level == "moderate"
    assert forked.snapshot.experiences[0].record_id != changed.snapshot.experiences[0].record_id
    assert forked.genesis.identity == changed.genesis.identity


async def test_recall_cues_exclude_unperceived_player_narration(monkeypatch):
    value = heard(text="Visible speech")
    observed = observation().model_copy(
        update={"message_id": "m1", "player_request": "SECRET unseen action"}
    )
    original_build = appraisal_context.build
    seen = []

    def capture(mind, *, query="", **options):
        seen.append(query)
        return original_build(mind, query=query, **options)

    monkeypatch.setattr(appraisal_context, "build", capture)
    monkeypatch.setattr(
        cognition.inference, "request", AsyncMock(side_effect=RuntimeError("probe"))
    )
    with pytest.raises(RuntimeError, match="probe"):
        await cognition.deliberate(
            SimpleNamespace(),
            Settings(),
            Usage(),
            "npc",
            observed,
            {"authored_goal": "Keep bridges safe"},
            [],
            value,
        )
    assert seen == ["Visible speech"]
