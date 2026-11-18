"""Only unambiguous own speech can reduce surplus positive review references."""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from backend.engine.chpm import inference, json_contract, passages, rendering, runtime
from backend.engine.chpm.kernel import ChpmError
from backend.engine.chpm.schema import AgendaIntent
from backend.engine.chpm.state import load
from tests.test_chpm_runtime import prepared

FIRST = 'Lina: "The brass key. The one from the table."'
ACTION = "Lina offers the key to the traveler."
LAST = 'Lina: "Here. Keep it safe."'
TEXT = "\n".join([FIRST, ACTION, LAST])


def host():
    manager = prepared()
    manager.avatar = SimpleNamespace(name="Traveler")
    manager._chpm_turn.names = {"npc": "Lina"}
    manager._chpm_turn.present_names = {"npc": "Lina", "peer": "Mira"}
    return manager


def identifier(text, fragment):
    return next(key for key, value in passages.index(text).items() if fragment in value)


def supplied(text=TEXT):
    return {
        "matches": True,
        "evidence": [
            {"actor_id": "npc", "passage_id": identifier(text, "The brass key.")},
            {"actor_id": "npc", "passage_id": identifier(text, "Here.")},
        ],
        "actions": [{"actor_id": "npc", "passage_id": identifier(text, ACTION)}],
    }


def install(monkeypatch, body):
    returned = []

    def respond(_manager, _settings, _usage, _instruction, payload, schema, *_args, **_kwargs):
        value = schema.model_validate({"review_scope": payload["review_scope"], **body})
        returned.append(value.model_copy(deep=True))
        return value

    request = AsyncMock(side_effect=respond)
    repair = AsyncMock(side_effect=AssertionError("Reference selection needs no prose rewrite."))
    monkeypatch.setattr(inference, "request", request)
    monkeypatch.setattr(rendering, "_repair", repair)
    return request, repair, returned


@pytest.mark.parametrize("reverse", [False, True])
async def test_valid_speech_surplus_keeps_one_existing_anchor_and_the_original_action(
    monkeypatch, reverse
):
    manager = host()
    body = supplied()
    if reverse:
        body["evidence"].reverse()
    request, repair, returned = install(monkeypatch, body)
    before = deepcopy(manager.state.entity_states)

    assert (
        await rendering.validate(
            manager, TEXT, completed=True, resolution="", system_prompt="Policy"
        )
        == TEXT
    )

    verdict = manager._chpm_turn.verdict
    available = passages.index(TEXT)
    assert [entry.quote for entry in verdict.evidence] == [
        available[body["evidence"][0]["passage_id"]]
    ]
    assert [entry.quote for entry in verdict.actions] == [ACTION]
    assert verdict.agenda_evidence == [] and verdict.heard == [] and verdict.causal_updates == []
    assert len(returned[0].evidence) == 2  # Never rewrite the provider's accepted DTO in place.
    assert manager.state.entity_states == before
    request.assert_awaited_once()
    repair.assert_not_awaited()


async def test_representative_speech_and_action_keep_their_actual_reply_sources(monkeypatch):
    manager = host()
    install(monkeypatch, supplied())
    await rendering.validate(manager, TEXT, completed=True, resolution="", system_prompt="Policy")
    reply = SimpleNamespace(
        id="reply", revision_id="reply-revision", role="assistant", content=TEXT, scene_id="room"
    )

    runtime.finish(manager, reply, completed=True)

    saved = load(manager.state)
    memories = saved.memories["npc"]
    assert {entry.kind for entry in memories} == {"own_speech", "own_action"}
    assert all(entry.source_message_id == reply.id and entry.quote in TEXT for entry in memories)
    assert saved.actors["npc"].action_evidence == ACTION
    assert saved.actors["npc"].spoken_evidence == passages.index(TEXT)["p0"]
    assert not saved.agenda


@pytest.mark.parametrize(
    "replacement",
    [
        'Mira: "Here."',
        'Traveler: "Here."',
        'Unknown: "Here."',
        "Lina thought: Here.",
        "Lina offers another key. Here.",
        '"Here."',
        'Lina: "Here." Mira: "Stop."',
        'Lina: "Here." She thought about it.',
        "Lina: Here.",
    ],
)
@pytest.mark.parametrize("bad_first", [False, True])
async def test_non_speech_or_foreign_surplus_is_never_discarded(
    monkeypatch, replacement, bad_first
):
    manager = host()
    text = "\n".join([FIRST, ACTION, replacement])
    body = supplied(text)
    if bad_first:
        body["evidence"].reverse()
    request, repair, _ = install(monkeypatch, body)

    with pytest.raises(ChpmError):
        await rendering.validate(
            manager, text, completed=True, resolution="", system_prompt="Policy"
        )

    assert manager._chpm_turn.verdict is None and not load(manager.state).actors
    request.assert_awaited_once()
    repair.assert_not_awaited()


@pytest.mark.parametrize(
    "problem",
    ["scope", "passage", "actor", "null", "ambiguous", "missing", "player_missing", "player_name"],
)
async def test_surplus_cannot_hide_invalid_or_unavailable_attribution(monkeypatch, problem):
    manager = host()
    body = supplied()
    if problem == "scope":
        body["review_scope"] = "stale-scope"
    if problem == "passage":
        body["evidence"][-1]["passage_id"] = "missing"
    if problem == "actor":
        body["evidence"][-1]["actor_id"] = "unavailable"
    if problem == "null":
        body["evidence"][-1]["passage_id"] = None
    if problem == "ambiguous":
        manager._chpm_turn.present_names["peer"] = "Lina"
    if problem == "missing":
        manager._chpm_turn.present_names = {}
    if problem == "player_missing":
        manager.avatar = None
    if problem == "player_name":
        manager.avatar.name = "Lina"
    _, repair, _ = install(monkeypatch, body)

    with pytest.raises(ChpmError):
        await rendering.validate(
            manager, TEXT, completed=True, resolution="", system_prompt="Policy"
        )

    assert manager._chpm_turn.verdict is None
    repair.assert_not_awaited()


async def test_distinct_agenda_anchors_keep_the_existing_strict_selection_rule(monkeypatch):
    manager = host()
    manager._chpm_turn.decisions["npc"].selected.agenda_change = AgendaIntent(
        action="commitment", text="Keep the key safe."
    )
    request, repair, _ = install(monkeypatch, supplied())

    with pytest.raises(ChpmError):
        await rendering.validate(
            manager, TEXT, completed=True, resolution="", system_prompt="Policy"
        )

    assert not load(manager.state).agenda and manager._chpm_turn.verdict is None
    request.assert_awaited_once()
    repair.assert_not_awaited()


async def test_reducing_speech_does_not_discard_duplicate_actions(monkeypatch):
    manager = host()
    body = supplied()
    body["actions"].append(deepcopy(body["actions"][0]))
    install(monkeypatch, body)

    with pytest.raises(ChpmError):
        await rendering.validate(
            manager, TEXT, completed=True, resolution="", system_prompt="Policy"
        )

    assert manager._chpm_turn.verdict is None


def test_provider_anchor_cap_and_global_dto_limit_remain_unchanged():
    body = {"review_scope": "current", **supplied()}
    parsed = passages.SharedReview.model_validate(body)
    assert len(parsed.evidence) == 2
    schema = json_contract.response_schema(
        passages.SharedReview,
        {
            "actor_id": ["npc"],
            "passage_id": list(passages.index(TEXT)),
            "review_scope": ["current"],
        },
    )
    assert schema["properties"]["evidence"]["maxItems"] == 1
    assert not Draft202012Validator(schema).is_valid(body)
    assert passages.SharedReview.model_json_schema()["properties"]["evidence"]["maxItems"] == 20


@pytest.mark.parametrize(
    "name,label", [("Лина", "Лина:"), ("Lina", "**Lina:**"), ("Lina", "**Lina**:")]
)
async def test_explicit_known_labels_need_no_language_or_style_guessing(monkeypatch, name, label):
    manager = host()
    manager._chpm_turn.names["npc"] = name
    manager._chpm_turn.present_names["npc"] = name
    action = f"{name} offers the key."
    text = f"{label} «The brass key. The one from the table.»\n{action}\n{label} «Here.»"
    body = {
        "matches": True,
        "evidence": [
            {"actor_id": "npc", "passage_id": identifier(text, "The brass key.")},
            {"actor_id": "npc", "passage_id": identifier(text, "Here.")},
        ],
        "actions": [{"actor_id": "npc", "passage_id": identifier(text, action)}],
    }
    request, repair, _ = install(monkeypatch, body)

    await rendering.validate(manager, text, completed=True, resolution="", system_prompt="Policy")

    assert len(manager._chpm_turn.verdict.evidence) == 1
    assert manager._chpm_turn.verdict.actions[0].quote == action
    request.assert_awaited_once()
    repair.assert_not_awaited()


async def test_the_existing_player_label_is_not_an_unambiguous_npc_speaker(monkeypatch):
    manager = host()
    manager._chpm_turn.present_names["npc"] = "You"
    text = "\n".join([FIRST.replace("Lina:", "You:"), ACTION, LAST.replace("Lina:", "You:")])
    install(monkeypatch, supplied(text))

    with pytest.raises(ChpmError):
        await rendering.validate(
            manager, text, completed=True, resolution="", system_prompt="Policy"
        )

    assert manager._chpm_turn.verdict is None


async def test_another_actors_single_agenda_anchor_is_retained_exactly(monkeypatch):
    manager = host()
    turn = manager._chpm_turn
    turn.names["peer"] = "Mira"
    turn.decisions["peer"] = turn.decisions["npc"].model_copy(
        deep=True, update={"actor_id": "peer"}
    )
    turn.decisions["peer"].selected.agenda_change = AgendaIntent(
        action="commitment", text="Return tomorrow."
    )
    promise = 'Mira: "I will return tomorrow."'
    text = TEXT + "\n" + promise
    body = supplied(text)
    promise_id = identifier(text, promise)
    body["evidence"].append({"actor_id": "peer", "passage_id": promise_id})
    request, repair, _ = install(monkeypatch, body)

    await rendering.validate(manager, text, completed=True, resolution="", system_prompt="Policy")

    assert [entry.actor_id for entry in turn.verdict.evidence] == ["npc", "peer"]
    assert [(entry.actor_id, entry.quote) for entry in turn.verdict.agenda_evidence] == [
        ("peer", promise)
    ]
    assert turn.verdict.actions[0].quote == ACTION
    request.assert_awaited_once()
    repair.assert_not_awaited()


async def test_silent_defer_does_not_gain_a_speech_normalization_path(monkeypatch):
    manager = host()
    manager._chpm_turn.decisions["npc"].selected.kind = "DEFER"
    install(monkeypatch, supplied())

    with pytest.raises(ChpmError):
        await rendering.validate(
            manager, TEXT, completed=True, resolution="", system_prompt="Policy"
        )

    assert manager._chpm_turn.verdict is None


async def test_internal_dto_overflow_cannot_hide_behind_representative_selection(monkeypatch):
    manager = host()

    def respond(_manager, _settings, _usage, _instruction, payload, schema, *_args, **_kwargs):
        value = schema.model_validate({"review_scope": payload["review_scope"], **supplied()})
        return value.model_copy(update={"evidence": [value.evidence[0]] * 21})

    monkeypatch.setattr(inference, "request", AsyncMock(side_effect=respond))

    with pytest.raises(ValidationError):
        await rendering.validate(
            manager, TEXT, completed=True, resolution="", system_prompt="Policy"
        )

    assert manager._chpm_turn.verdict is None
