"""Completed agenda-evidence rejection uses the existing bounded narration repair."""

from copy import deepcopy

import pytest

from backend.engine.chpm import agenda, inference, passages, rendering
from backend.engine.chpm.errors import InferenceUnavailableError
from backend.engine.chpm.kernel import ChpmError
from backend.engine.chpm.schema import AgendaIntent
from backend.engine.chpm.state import load
from tests.test_chpm_runtime import prepared

ORIGINAL = "Rin: I will repair the bridge.\n\nRin: Thanks."
REPAIRED = "Rin: I will repair the bridge.\n\nRin: That is my commitment."
ISSUE = "CHPM agenda update needs exact evidence in the owner's own speech."


def host_with_agenda():
    host = prepared()
    host._chpm_turn.decisions["npc"].selected.agenda_change = AgendaIntent(
        action="commitment", text="Repair the bridge"
    )
    return host


def review_for(available, *, invalid=False, agenda_change=True):
    ids = list(available)
    speech = ids[-1] if invalid else ids[0]
    return passages.Review(
        matches=True,
        evidence=[{"actor_id": "npc", "passage_id": speech}],
        agenda_evidence=[{"actor_id": "npc", "passage_id": ids[0]}] if agenda_change else [],
    )


def install(monkeypatch, host, *, repeated=False, unavailable=None, invalid_first=True):
    events = []
    repair_issues = []

    async def request(manager, settings, usage, instruction, payload, schema, phase, **kwargs):
        inference.reserve(settings, usage, 1)
        events.append("review")
        number = events.count("review")
        if unavailable == f"review{number}":
            raise InferenceUnavailableError("An uncertain provider request must not be repeated.")
        return review_for(
            payload["passages"],
            invalid=(number == 1 and invalid_first) or (number > 1 and repeated),
            agenda_change=bool(host._chpm_turn.decisions["npc"].selected.agenda_change),
        )

    async def repair(manager, turn, text, resolution, issues, system_prompt):
        inference.reserve(turn.initial.settings, turn.usage, 1)
        turn.usage.repairs += 1
        events.append("repair")
        repair_issues.append(issues)
        if unavailable == "repair":
            raise InferenceUnavailableError("An uncertain repair must not be repeated.")
        return REPAIRED

    monkeypatch.setattr(inference, "request", request)
    monkeypatch.setattr(rendering, "_repair", repair)
    return events, repair_issues


async def validate(host):
    return await rendering.validate(
        host, ORIGINAL, completed=True, resolution="", system_prompt="Keep the original policy."
    )


async def test_completed_mismatched_agenda_anchor_uses_one_reserved_repair_and_repeat_review(
    monkeypatch,
):
    host = host_with_agenda()
    turn = host._chpm_turn
    decisions = deepcopy(turn.decisions)
    settings = turn.initial.settings.model_dump()
    events, issues = install(monkeypatch, host)

    assert await validate(host) == REPAIRED

    assert events == ["review", "repair", "review"]
    assert issues == [[ISSUE]]
    assert turn.usage.calls == 3 and turn.usage.repairs == 1
    assert turn.usage.status == "validated" and turn.verdict.matches
    assert turn.decisions == decisions and turn.initial.settings.model_dump() == settings
    assert load(host.state).agenda == []
    agenda.validate_evidence(turn.decisions, turn.verdict)


async def test_repeated_bad_agenda_evidence_remains_strictly_rejected_without_a_ledger_write(
    monkeypatch,
):
    host = host_with_agenda()
    events, issues = install(monkeypatch, host, repeated=True)

    with pytest.raises(ChpmError, match="after one repair"):
        await validate(host)

    assert events == ["review", "repair", "review"] and issues == [[ISSUE]]
    assert host._chpm_turn.usage.calls == 3 and host._chpm_turn.usage.repairs == 1
    assert host._chpm_turn.verdict is None and load(host.state).agenda == []


async def test_insufficient_existing_reserve_rejects_without_an_additional_request(monkeypatch):
    host = host_with_agenda()
    turn = host._chpm_turn
    turn.initial.settings.max_calls_per_turn = 3
    turn.usage.calls = 2
    events, issues = install(monkeypatch, host)

    with pytest.raises(ChpmError, match="after one repair"):
        await validate(host)

    assert events == ["review"] and issues == []
    assert turn.usage.calls == 3 and turn.usage.repairs == 0
    assert turn.verdict is None and load(host.state).agenda == []


@pytest.mark.parametrize("unavailable", ["review1", "repair", "review2"])
async def test_uncertain_transport_never_adds_a_retry_or_further_repair(monkeypatch, unavailable):
    host = host_with_agenda()
    events, _issues = install(monkeypatch, host, unavailable=unavailable)

    with pytest.raises(ChpmError):
        await validate(host)

    expected = {
        "review1": ["review"],
        "repair": ["review", "repair"],
        "review2": ["review", "repair", "review"],
    }[unavailable]
    assert events == expected and host._chpm_turn.usage.calls == len(expected)
    assert host._chpm_turn.verdict is None and load(host.state).agenda == []


@pytest.mark.parametrize("with_agenda", [False, True])
async def test_valid_review_keeps_the_existing_single_request_path(monkeypatch, with_agenda):
    host = host_with_agenda() if with_agenda else prepared()
    events, issues = install(monkeypatch, host, invalid_first=False)

    assert await validate(host) == ORIGINAL
    assert events == ["review"] and issues == []
    assert host._chpm_turn.usage.calls == 1 and host._chpm_turn.usage.repairs == 0
    assert host._chpm_turn.usage.status == "validated" and load(host.state).agenda == []


async def test_unknown_passage_reference_keeps_its_existing_failure_boundary(monkeypatch):
    host = host_with_agenda()
    events, _issues = install(monkeypatch, host)

    async def request(*_args, **_kwargs):
        events.append("unknown_reference")
        return passages.Review(
            matches=True, evidence=[{"actor_id": "npc", "passage_id": "not_in_the_text"}]
        )

    monkeypatch.setattr(inference, "request", request)
    with pytest.raises(ChpmError, match="unknown passage"):
        await validate(host)
    assert events == ["unknown_reference"] and load(host.state).agenda == []
