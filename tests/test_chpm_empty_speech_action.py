"""A redundant empty speech anchor does not suppress a separately reviewed own action."""

from copy import deepcopy
from unittest.mock import AsyncMock

import pytest

from backend.engine.chpm import expression, inference, passages, rendering
from backend.engine.chpm.kernel import ChpmError
from backend.engine.chpm.schema import AgendaIntent
from backend.engine.chpm.state import load
from tests.test_chpm_action_expression import TEXT, deliver, review
from tests.test_chpm_review_anchor_capacity import decisions
from tests.test_chpm_runtime import prepared


def empty_speech():
    return review(evidence=[{"actor_id": "npc", "passage_id": None}])


async def test_empty_speech_with_exact_own_action_delivers_only_action_memory(monkeypatch):
    checked = empty_speech()
    original = checked.model_dump()
    host, saved, request = await deliver(monkeypatch, value=checked)
    chosen = saved.actors["npc"]
    assert chosen.status == "delivered" and chosen.action_evidence == TEXT
    assert chosen.spoken_evidence == ""
    assert chosen.action_evidence_span is not None
    assert chosen.action_evidence_span.matches(TEXT, TEXT)
    assert [entry.kind for entry in saved.memories["npc"]] == ["own_action"]
    assert saved.memories["npc"][0].quote == TEXT
    assert checked.model_dump() == original
    assert "map" not in host.state.entity_states
    request.assert_awaited_once()


def test_redundant_empty_speech_preserves_another_actors_real_speech():
    text = TEXT + '\nMira: "I will stay here."'
    checked = passages.Review.model_validate(
        {
            "matches": True,
            "evidence": [
                {"actor_id": "npc", "passage_id": None},
                {"actor_id": "mira", "passage_id": "p1"},
            ],
            "actions": [{"actor_id": "npc", "passage_id": "p0"}],
        }
    )
    verdict = passages.resolve(checked, passages.index(text), text=text)
    original = deepcopy(verdict)
    expression.validate(decisions(["npc", "mira"]), verdict, text)
    assert verdict == original
    assert verdict.evidence[0].quote == ""
    assert verdict.evidence[1].quote == 'Mira: "I will stay here."'


@pytest.mark.parametrize(
    ("changes", "extra_actor", "message"),
    [
        ({"actions": []}, False, "no exact speech evidence"),
        ({"actions": [{"actor_id": "npc", "passage_id": None}]}, False, "no exact action evidence"),
        (
            {"actions": [{"actor_id": "npc", "passage_id": "missing"}]},
            False,
            "unknown passage reference",
        ),
        ({"actions": [{"actor_id": "other", "passage_id": "p0"}]}, False, "exactly once"),
        ({"evidence": [{"actor_id": "npc", "passage_id": None}] * 2}, False, "exactly once"),
        (
            {
                "evidence": [
                    {"actor_id": "npc", "passage_id": None},
                    {"actor_id": "npc", "passage_id": "p0"},
                ]
            },
            False,
            "exactly once",
        ),
        ({"actions": [{"actor_id": "npc", "passage_id": "p0"}] * 2}, False, "exactly once"),
        ({"evidence": [{"actor_id": "other", "passage_id": None}]}, False, "exactly once"),
        (
            {
                "evidence": [{"actor_id": "other", "passage_id": None}],
                "actions": [{"actor_id": "other", "passage_id": "p0"}],
            },
            False,
            "exactly once",
        ),
        ({}, True, "exactly once"),
        (
            {"actions": [{"actor_id": "other", "passage_id": "p0"}]},
            True,
            "no exact speech evidence",
        ),
    ],
    ids=[
        "missing-action",
        "null-action",
        "unknown-action-passage",
        "other-action-actor",
        "duplicate-empty-speech",
        "duplicate-mixed-speech",
        "duplicate-actions",
        "unknown-speech-actor",
        "unknown-actor-in-both",
        "missing-controlled-actor",
        "cross-actor-action",
    ],
)
async def test_empty_speech_does_not_bypass_actor_or_action_validation(
    monkeypatch, changes, extra_actor, message
):
    host = prepared()
    checked = review(**{"evidence": [{"actor_id": "npc", "passage_id": None}], **changes})
    if extra_actor:
        host._chpm_turn.decisions["other"] = host._chpm_turn.decisions["npc"].model_copy(
            update={"actor_id": "other"}, deep=True
        )
    request = AsyncMock(return_value=checked)
    monkeypatch.setattr(inference, "request", request)
    with pytest.raises(ChpmError, match=message):
        await rendering.validate(host, TEXT, completed=True, resolution="", system_prompt="Policy")
    assert not load(host.state).actors
    request.assert_awaited_once()


@pytest.mark.parametrize("boundary", ["hearing", "agenda"])
async def test_valid_action_with_empty_speech_keeps_hearing_and_agenda_strict(
    monkeypatch, boundary
):
    host = prepared()
    changes = {"evidence": [{"actor_id": "npc", "passage_id": None}]}
    if boundary == "hearing":
        changes["heard"] = [{"actor_id": "npc", "speaker_id": "npc", "passage_id": "p0"}]
        message = "hearing evidence"
    else:
        host._chpm_turn.decisions["npc"].selected.agenda_change = AgendaIntent(
            action="commitment", text="Bring the map tomorrow."
        )
        changes["agenda_evidence"] = [{"actor_id": "npc", "passage_id": "p0"}]
        message = "agenda update needs exact evidence"
    monkeypatch.setattr(inference, "request", AsyncMock(return_value=review(**changes)))
    with pytest.raises(ChpmError, match=message):
        await rendering.validate(host, TEXT, completed=True, resolution="", system_prompt="Policy")
    assert not load(host.state).actors and not load(host.state).agenda
