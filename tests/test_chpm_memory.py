"""Per-observer memory preserves quotes without promoting claims into facts."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.engine.chpm import context, inference, memory, perception, rendering, runtime
from backend.engine.chpm.kernel import ChpmError, digest
from backend.engine.chpm.schema import HeardSpeech, KernelState, Perception, Projection, Settings
from backend.engine.chpm.state import KEY, load, retract
from tests.test_chpm_kernel import grounded_proposal, observation
from tests.test_chpm_runtime import accepted, manager, prepared


def source(message_id="message", content="I will look into it.", **changes):
    return SimpleNamespace(
        **{
            "id": message_id,
            "content": content,
            "revision_id": "v1",
            "role": "assistant",
            "scene_id": "room",
            "session_id": "session",
            **changes,
        }
    )


def entry(message_id="message", content="I will look into it.", observer="npc"):
    return memory.from_source(
        source(message_id, content), observer, observer, content, "own_speech"
    )


def test_projection_rejects_foreign_observers_fabricated_and_repeated_quotes():
    valid = Projection(audience=[Perception(actor_id="npc", quotes=["Hello"])])
    assert perception.validate_projection(valid, "Hello (private thought)", {"npc"})[
        "npc"
    ].quotes == ["Hello"]
    for result in [
        Projection(audience=[Perception(actor_id="absent", quotes=["Hello"])]),
        Projection(audience=[Perception(actor_id="npc", quotes=["Invented"])]),
        Projection(audience=[Perception(actor_id="npc", quotes=["Hello", "Hello"])]),
    ]:
        with pytest.raises(ChpmError):
            perception.validate_projection(result, "Hello", {"npc"})


async def test_private_player_text_never_reaches_individual_cognition(monkeypatch):
    host, actor = manager()
    private = "Hello. (Privately: SECRET_DOOR_CODE is 417.)"
    monkeypatch.setattr(
        context,
        "observation",
        AsyncMock(return_value=observation(player_request=private, content_hash=digest(private))),
    )
    monkeypatch.setattr(context, "available", lambda *_: True)
    monkeypatch.setattr(runtime, "release_for_model", AsyncMock())
    projector = AsyncMock(return_value={"npc": Perception(actor_id="npc", quotes=["Hello."])})
    monkeypatch.setattr(perception, "project", projector)
    proposal_call = AsyncMock(return_value=grounded_proposal())
    monkeypatch.setattr(inference, "request", proposal_call)
    await runtime.prepare(host, private, [actor])
    payload = proposal_call.call_args.args[4]
    assert "SECRET_DOOR_CODE" not in str(payload)
    assert payload["observation"]["player_request"] == "Hello."
    assert projector.call_args.args[3] == private


async def test_new_scene_npcs_do_not_receive_the_old_scene_request(monkeypatch):
    host, actor = manager()
    monkeypatch.setattr(
        context, "observation", AsyncMock(return_value=observation(source_scene_id="private-room"))
    )
    monkeypatch.setattr(context, "available", lambda *_: True)
    monkeypatch.setattr(runtime, "release_for_model", AsyncMock())
    projector = AsyncMock(side_effect=AssertionError("Must not project across scenes"))
    monkeypatch.setattr(perception, "project", projector)
    called = AsyncMock(return_value=grounded_proposal())
    monkeypatch.setattr(inference, "request", called)
    await runtime.prepare(host, "Private conversation before leaving", [actor])
    payload = called.call_args.args[4]
    assert payload["observation"]["player_request"] == ""
    assert payload["observation"]["perception_uncertain"] is True
    projector.assert_not_called()


@pytest.mark.parametrize(
    "change", ["revision", "content", "session", "role", "observer", "missing"]
)
def test_memory_checks_all_source_dimensions(change):
    stored = entry()
    original = source()
    assert memory.valid_source(stored, original, "npc", "session")
    if change == "revision":
        original.revision_id = "v2"
    elif change == "content":
        original.content += " Edited."
    elif change == "session":
        original.session_id = "other-session"
    elif change == "role":
        original.role = "user"
    elif change == "observer":
        stored.observer_id = "other-npc"
    else:
        original = None
    assert not memory.valid_source(stored, original, "npc", "session")


def test_window_deduplicates_and_reports_eviction_without_mutating_sources():
    state = KernelState(settings=Settings(memory_limit=2))
    first = entry("1", "First statement")
    memory.append(state, "npc", [first, first.model_copy()])
    assert state.memories["npc"] == [first]
    memory.append(state, "npc", [entry("2", "Second statement"), entry("3", "Third statement")])
    assert [item.source_message_id for item in state.memories["npc"]] == ["2", "3"]
    assert state.usage.memory_evictions == 1
    assert first.quote == "First statement"
    state.settings.memory_limit = 0
    memory.append(state, "npc", [])
    assert state.memories["npc"] == []


async def test_recall_omits_edited_sources_and_preserves_observer_boundaries():
    host, _ = manager()
    host.db = SimpleNamespace(
        scalars=AsyncMock(return_value=[source("good", "Good"), source("edited", "Changed")])
    )
    values = [
        entry("good", "Good"),
        entry("edited", "Old"),
        entry("good", "Good", observer="other"),
    ]
    recalled = await memory.recall(host, "npc", values, 12)
    assert [value.quote for value in recalled] == ["Good"]
    assert values[1].quote == "Old"


def test_retraction_removes_source_memory_and_invalidates_decisions():
    state = KernelState(memories={"npc": [entry("old"), entry("keep")]})
    host = SimpleNamespace(entity_states={KEY: state.model_dump()})
    retract(host, "old")
    assert [value.source_message_id for value in load(host).memories["npc"]] == ["keep"]


@pytest.mark.parametrize(
    "speaker,observer,quote",
    [
        ("absent", "npc", "Let us discuss the repair."),
        ("npc", "npc", "Let us discuss the repair."),
        ("other", "absent", "Let us discuss the repair."),
        ("other", "npc", "Invented speech"),
    ],
)
async def test_review_rejects_impossible_hearing(monkeypatch, speaker, observer, quote):
    host = prepared()
    host._chpm_turn.present_names = {"npc": "Rin", "other": "Miki"}
    result = accepted()
    result.heard = [HeardSpeech(actor_id=observer, speaker_id=speaker, quote=quote)]
    monkeypatch.setattr(inference, "request", AsyncMock(return_value=result))
    with pytest.raises(ChpmError, match="hearing evidence"):
        await rendering.validate(
            host,
            "Let us discuss the repair.",
            completed=True,
            resolution="",
            system_prompt="Policy",
        )
