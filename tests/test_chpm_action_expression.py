"""An NPC can express a reviewed intention by acting without speaking for anyone."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from backend.engine.chpm import (
    cognitive_context,
    context,
    host_adapter,
    inference,
    passages,
    prompts,
    rendering,
    runtime,
)
from backend.engine.chpm.appraisal_contracts import INSTRUCTIONS
from backend.engine.chpm.host_state import Source, record
from backend.engine.chpm.kernel import ChpmError
from backend.engine.chpm.lifecycle import fork
from backend.engine.chpm.schema import AgendaIntent, KernelState, MemoryEntry, Settings
from backend.engine.chpm.semantic_choice import previous_context
from backend.engine.chpm.state import KEY, load, retract
from tests.test_chpm_host_state import mind
from tests.test_chpm_kernel import observation
from tests.test_chpm_runtime import prepared

TEXT = "Rin folds her map and places it on the table."


def review(text=TEXT, **changes):
    identifier = next(iter(passages.index(text)))
    return passages.Review.model_validate(
        {
            "matches": True,
            "evidence": [],
            "actions": [{"actor_id": "npc", "passage_id": identifier}],
            **changes,
        }
    )


def reply(text=TEXT):
    return SimpleNamespace(
        id="action-reply", revision_id="v1", content=text, role="assistant", scene_id="room"
    )


async def deliver(monkeypatch, *, value=None):
    host = prepared()
    host._chpm_turn.decisions["npc"].selected.intention = "Fold my map and put it on the table."
    request = AsyncMock(return_value=value or review())
    monkeypatch.setattr(inference, "request", request)
    assert (
        await rendering.validate(host, TEXT, completed=True, resolution="", system_prompt="Policy")
        == TEXT
    )
    runtime.finish(host, reply(), completed=True)
    return host, load(host.state), request


async def test_action_only_expression_needs_no_dialogue_or_extra_approval_call(monkeypatch):
    host, saved, request = await deliver(monkeypatch)
    chosen = saved.actors["npc"]
    assert chosen.status == "delivered" and chosen.action_evidence == TEXT
    assert chosen.spoken_evidence == ""
    assert [entry.kind for entry in saved.memories["npc"]] == ["own_action"]
    assert saved.memories["npc"][0].quote == TEXT
    assert "map" not in host.state.entity_states  # Expression is not a second world-state owner.
    request.assert_awaited_once()


async def test_mixed_expression_keeps_speech_and_action_evidence_separate(monkeypatch):
    text = 'Rin folds her map and places it on the table.\nRin: "I am staying here."'
    available = passages.index(text)
    action_id = next(key for key, value in available.items() if value == TEXT)
    speech_id = next(key for key, value in available.items() if "I am staying" in value)
    host = prepared()
    checked = passages.Review.model_validate(
        {
            "matches": True,
            "evidence": [{"actor_id": "npc", "passage_id": speech_id}],
            "actions": [{"actor_id": "npc", "passage_id": action_id}],
        }
    )
    monkeypatch.setattr(inference, "request", AsyncMock(return_value=checked))
    await rendering.validate(host, text, completed=True, resolution="", system_prompt="Policy")
    runtime.finish(host, reply(text), completed=True)
    saved = load(host.state)
    assert saved.actors["npc"].action_evidence == TEXT
    assert "I am staying" in saved.actors["npc"].spoken_evidence
    assert {entry.kind for entry in saved.memories["npc"]} == {"own_speech", "own_action"}
    updated = host_adapter.finish(
        SimpleNamespace(minds={"npc": mind()}), reply(text), saved.memories["npc"], "npc", minute=5
    )
    assert {source.kind for source in updated.sources.values()} == {"speech", "narration"}
    # Two views of the same reply are not independent confirmations.
    assert len({tuple(entry.root_ids) for entry in updated.snapshot.evidence}) == 1


@pytest.mark.parametrize("problem", ["unknown", "duplicate", "missing", "empty"])
async def test_actions_do_not_bypass_actor_coverage_or_exact_sources(monkeypatch, problem):
    host = prepared()
    checked = review()
    if problem == "unknown":
        checked.actions[0].actor_id = "another-npc"
    if problem == "duplicate":
        checked.actions.append(checked.actions[0].model_copy())
    if problem == "missing":
        checked.actions[0].passage_id = "missing"
    if problem == "empty":
        checked.actions[0].passage_id = None
    monkeypatch.setattr(inference, "request", AsyncMock(return_value=checked))
    with pytest.raises(ChpmError):
        await rendering.validate(host, TEXT, completed=True, resolution="", system_prompt="Policy")
    assert not load(host.state).actors


async def test_an_action_alone_cannot_publish_a_spoken_commitment(monkeypatch):
    host = prepared()
    host._chpm_turn.decisions["npc"].selected.agenda_change = AgendaIntent(
        action="commitment", text="Bring the map tomorrow."
    )
    checked = review(agenda_evidence=[{"actor_id": "npc", "passage_id": "p0"}])
    monkeypatch.setattr(inference, "request", AsyncMock(return_value=checked))
    with pytest.raises(ChpmError):
        await rendering.validate(host, TEXT, completed=True, resolution="", system_prompt="Policy")
    assert not load(host.state).agenda


async def test_action_memory_remains_narration_and_never_becomes_heard_speech(monkeypatch):
    _, saved, _ = await deliver(monkeypatch)
    turn = SimpleNamespace(minds={"npc": mind()})
    updated = host_adapter.finish(turn, reply(), saved.memories["npc"], "npc", minute=5)
    source = next(value for value in updated.sources.values() if value.message_id == reply().id)
    assert source.kind == "narration" and source.reported and source.facts is None
    assert source.speaker_id == "npc" and source.report is None
    previous = previous_context(updated, saved.actors["npc"], observation(message_id="next"))
    assert previous is not None and previous.action_evidence == TEXT
    assert previous.spoken_evidence == ""


async def test_previous_action_requires_its_own_retained_exact_source(monkeypatch):
    _, saved, _ = await deliver(monkeypatch)
    prior = saved.actors["npc"]
    for changes in ({"content_hash": "edited"}, {"speaker_id": "other"}, {"kind": "speech"}):
        source = Source(
            message_id=prior.reply_id,
            revision_id=prior.reply_revision,
            content_hash=prior.reply_hash,
            role="assistant",
            speaker_id="npc",
            kind="narration",
            text=TEXT,
        ).model_copy(update=changes)
        updated = record(mind(), source, minute=5)
        assert previous_context(updated, prior, observation(message_id="next")) is None


@pytest.mark.parametrize("changes", [{"speaker_id": "other"}, {"source_role": "user"}])
def test_own_action_memory_cannot_be_forged_as_another_actors_action(changes):
    with pytest.raises(ValidationError):
        MemoryEntry(
            source_message_id="reply",
            source_hash="hash",
            source_role=changes.get("source_role", "assistant"),
            scene_id="room",
            observer_id="npc",
            speaker_id=changes.get("speaker_id", "npc"),
            kind="own_action",
            quote=TEXT,
        )


async def test_own_action_context_does_not_label_actions_as_utterances(monkeypatch):
    host, saved, _ = await deliver(monkeypatch)
    actor = SimpleNamespace(
        id="npc", name="Rin", character="Engineer", goal="Repair the bridge", metadata_json={}
    )
    supplied = await context.actor_context(host, actor, None, saved.memories["npc"])
    assert supplied["witnessed_utterances_not_world_facts"] == []
    assert supplied["own_action_observations_not_world_facts"][0]["quote"] == TEXT


def test_own_action_window_obeys_existing_input_tiers_without_mutating_memory():
    value = mind()
    supplied = {
        "authored_character": value.genesis.identity.description,
        "authored_goal": value.genesis.identity.authored_goals[0],
        "own_action_observations_not_world_facts": [{"quote": "A remembered action. " * 90}] * 12,
        "observation": observation().model_dump(),
    }
    _, _, payload, _ = cognitive_context.pack(
        value, observation(), supplied, [], Settings(), prompts.PROPOSE + INSTRUCTIONS
    )
    assert payload["context_packing"]["action_entries_omitted"] > 0
    assert len(supplied["own_action_observations_not_world_facts"]) == 12


async def test_action_provenance_survives_fork_and_retracts_with_its_source(monkeypatch):
    host, saved, _ = await deliver(monkeypatch)
    saved.minds["npc"] = host_adapter.finish(
        SimpleNamespace(minds={"npc": mind()}), reply(), saved.memories["npc"], "npc", minute=5
    )
    original_identity = saved.minds["npc"].genesis.identity
    raw = {KEY: saved.model_dump()}
    copied = load(
        SimpleNamespace(entity_states=fork(raw, {reply().id: "copy-action"}, "copy-session"))
    )
    assert copied.memories["npc"][0].kind == "own_action"
    assert copied.memories["npc"][0].source_message_id == "copy-action"
    assert copied.minds["npc"].genesis.identity == original_identity
    assert {source.kind for source in copied.minds["npc"].sources.values()} == {"narration"}
    host.state.entity_states[KEY] = saved.model_dump()
    retract(host.state, reply().id)
    restored = load(host.state)
    assert restored.memories["npc"] == [] and not restored.actors
    assert restored.minds["npc"].genesis.identity == original_identity


def test_legacy_saved_decisions_and_review_responses_keep_safe_defaults():
    host = prepared()
    raw = host._chpm_turn.initial.model_dump()
    decision = host._chpm_turn.decisions["npc"].model_dump()
    decision.pop("action_evidence")
    raw["actors"] = {"npc": decision}
    assert KernelState.model_validate(raw).actors["npc"].action_evidence == ""
    assert passages.Review(matches=True, evidence=[]).actions == []
