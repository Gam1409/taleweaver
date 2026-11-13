"""Rejected emotion and psychological updates remain observable without changing results."""

import json
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from pydantic import BaseModel

from backend.core.npc_presentation import PortraitPreferences
from backend.engine.chpm import inference, proposal_attempt, rendering, runtime, state
from backend.engine.chpm.kernel import ChpmError
from backend.engine.chpm.schema import Settings, Usage, Verdict
from backend.engine.npc_presentation import diagnostics
from backend.engine.npc_presentation import runtime as presentation
from tests.test_chpm_runtime import prepared


@pytest.fixture
def rejection(monkeypatch):
    observer = Mock()
    for module in (proposal_attempt, rendering, runtime, state, presentation, diagnostics):
        monkeypatch.setattr(module, "reject", observer, raising=False)
    return observer


class Candidate(BaseModel):
    value: str


async def test_repaired_chpm_proposal_retains_its_first_rejection(monkeypatch, rejection):
    request = AsyncMock(side_effect=[Candidate(value="invalid"), Candidate(value="accepted")])
    monkeypatch.setattr(inference, "request", request)

    def accept(candidate):
        if candidate.value == "invalid":
            raise ChpmError("The proposed feeling has no cited observation.")
        return candidate

    result = await proposal_attempt.request(
        SimpleNamespace(),
        Settings(mode="live", actor_ids=["npc"]),
        Usage(),
        "Authored policy",
        {"observed": "A quiet archive."},
        Candidate,
        {"actor_id": ["npc"]},
        accept,
    )
    assert result.value == "accepted" and request.await_count == 2
    rejection.assert_called_once()
    assert rejection.call_args.args[:2] == ("emotion", "chpm.proposal_invalid")
    assert rejection.call_args.kwargs["proposal"] == {"value": "invalid"}
    assert rejection.call_args.kwargs["context"] == {"observed": "A quiet archive."}


async def test_chpm_rejected_review_records_candidate_and_causal_contract(monkeypatch, rejection):
    host = prepared()
    initial = deepcopy(host.state.entity_states)
    monkeypatch.setattr(
        inference,
        "request",
        AsyncMock(return_value=Verdict(matches=False, issues=["Added a promise"])),
    )
    verdict = await rendering._review(
        host, host._chpm_turn, "An unsupported promise.", "No promise"
    )
    assert not verdict.matches and host.state.entity_states == initial
    rejection.assert_called_once()
    assert rejection.call_args.args[:2] == ("emotion", "chpm.narration_rejected")
    assert rejection.call_args.kwargs["narration"] == "An unsupported promise."
    assert rejection.call_args.kwargs["host_resolution"] == "No promise"


async def test_rejected_review_does_not_recompute_its_original_context(monkeypatch, rejection):
    host = prepared()
    payload = {"existing_context": "Keep this exact reviewed input."}
    context = Mock(side_effect=[payload, AssertionError("Context must not be reconstructed")])
    monkeypatch.setattr(rendering, "_review_payload", context)
    monkeypatch.setattr(
        inference, "request", AsyncMock(return_value=Verdict(matches=False, issues=["Mismatch"]))
    )
    verdict = await rendering._review(host, host._chpm_turn, "Candidate.", "Resolution.")
    assert not verdict.matches and context.call_count == 1
    assert rejection.call_args.kwargs["context"] is payload


@pytest.mark.parametrize("completed", [False, True])
def test_unconfirmed_chpm_commit_preserves_state_and_records_decisions(rejection, completed):
    host = prepared()
    initial = deepcopy(host.state.entity_states)
    if completed:
        with pytest.raises(ChpmError, match="without successful validation"):
            runtime.finish(host, SimpleNamespace(), completed=True)
    else:
        runtime.finish(host, SimpleNamespace(), completed=False)
    assert host.state.entity_states == initial
    assert rejection.called
    assert rejection.call_args.kwargs["decisions"]


@pytest.mark.parametrize("failure", ["stale", "invalid"])
def test_chpm_save_rejection_preserves_confirmed_state(rejection, failure):
    host = prepared()
    initial = deepcopy(host.state.entity_states)
    value = state.load(host.state)
    expected_revision = 1 if failure == "stale" else 0
    if failure == "invalid":
        value.settings.mode = "invalid"
    with pytest.raises(ChpmError):
        state.save(host.state, value, expected_revision=expected_revision)
    assert host.state.entity_states == initial
    rejection.assert_called_once()
    assert rejection.call_args.args[:2] == ("emotion", f"chpm.save_{failure}")
    assert "proposal" in rejection.call_args.kwargs


def _footer(entries):
    return "<npc-state>" + json.dumps({"npcs": entries}) + "</npc-state>"


def test_invalid_emotion_is_traced_even_when_valid_thought_is_retained(rejection):
    turn = presentation.PresentationTurn(
        PortraitPreferences(emotion_palette=True, character_thoughts=True), {"npc": "Keeper"}
    )
    entry = {"npc_id": "npc", "emotion": "joy", "intensity": "high", "thought": "I will wait."}
    assert turn.clean("Story." + _footer([entry])) == "Story."
    assert turn.payload("Story.")["npcs"] == {"npc": {"thought": "I will wait."}}
    rejection.assert_called_once()
    assert rejection.call_args.args[:2] == ("emotion", "presentation.invalid_emotion")
    assert rejection.call_args.kwargs["proposal"] == entry


@pytest.mark.parametrize("entry", [None, {"npc_id": "missing", "emotion": "joy", "intensity": 40}])
def test_unavailable_or_malformed_presentation_entry_is_traced(rejection, entry):
    turn = presentation.PresentationTurn(
        PortraitPreferences(emotion_palette=True), {"npc": "Keeper"}
    )
    assert turn.clean("Story." + _footer([entry])) == "Story."
    assert turn.payload("Story.") is None
    rejection.assert_called_once()
    assert rejection.call_args.kwargs["proposal"] == entry


@pytest.mark.parametrize(
    "entries",
    [
        [],
        [{"npc_id": "npc", "emotion": "calm", "intensity": 0}],
        [{"npc_id": "npc", "emotion": "unknown", "intensity": 0}],
        [{"npc_id": "npc"}],
    ],
)
def test_explicit_no_assessment_or_neutral_presentation_is_not_a_rejection(rejection, entries):
    turn = presentation.PresentationTurn(
        PortraitPreferences(emotion_palette=True), {"npc": "Keeper"}
    )
    text = turn.clean("Story." + _footer(entries))
    turn.clean(text)  # Narrator validation can inspect already stripped prose again.
    diagnostics.report(
        SimpleNamespace(state=SimpleNamespace(session_id="session")), turn, text, completed=True
    )
    rejection.assert_not_called()


def test_missing_requested_presentation_is_an_unconfirmed_assessment(rejection):
    turn = presentation.PresentationTurn(
        PortraitPreferences(emotion_palette=True), {"npc": "Keeper"}
    )
    text = turn.clean("Story without requested metadata.")
    diagnostics.report(
        SimpleNamespace(state=SimpleNamespace(session_id="session")), turn, text, completed=True
    )
    rejection.assert_called_once()
    assert rejection.call_args.args[:2] == ("emotion", "presentation.missing_footer")
    assert rejection.call_args.kwargs["narration"] == text
