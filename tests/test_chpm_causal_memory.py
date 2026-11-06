"""Causal continuity keeps concrete circumstances, not just a task title."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.api.routes.adventures.chpm import _update_replay
from backend.engine.chpm import (
    agent,
    appraisal_context,
    causal_memory,
    context,
    inference,
    lifecycle,
    passages,
    runtime,
)
from backend.engine.chpm.agent_contracts import Step
from backend.engine.chpm.causal_contracts import Memory
from backend.engine.chpm.kernel import ChpmError
from backend.engine.chpm.schema import KernelState, Settings, Usage, Verdict
from backend.engine.chpm.state import KEY, load, retract
from tests.test_chpm_compact_contract import contract_fixture
from tests.test_chpm_kernel import observation
from tests.test_chpm_memory import source
from tests.test_chpm_runtime import manager

TEXT = "Rin secured the collected sample in her inner coat pocket for laboratory analysis."


def draft(text=TEXT, *, actor="npc"):
    reference = next(iter(passages.index(text)))
    return {
        "actor_id": actor,
        "action": "open",
        "facts": {
            "purpose": {"text": "Have the collected sample analysed", "passage_id": reference},
            "cause": {"text": "A sample has already been collected", "passage_id": reference},
            "consequence": {
                "text": "The sample is in Rin's inner coat pocket",
                "passage_id": reference,
            },
        },
    }


def opened():
    turn, mind = contract_fixture()
    state = KernelState(minds={"npc": mind})
    reply = source("sample", TEXT)
    turn.verdict = Verdict(matches=True, causal_updates=[draft()])
    causal_memory.apply(turn, state, reply, passages.index(reply.content))
    assert not state.usage.causal_notes
    return turn, state, reply


def test_arrival_changes_the_event_without_erasing_the_reason_or_existing_sample():
    turn, state, _ = opened()
    original = state.causal_memory.actors["npc"][0]
    arrival = source("arrival", "Rin reached the laboratory.")
    turn.causal_threads = {"npc": [original]}
    update = {
        "actor_id": "npc",
        "thread_id": original.id,
        "action": "update",
        "facts": {"event": {"text": "Rin reached the laboratory", "passage_id": "p0"}},
    }
    turn.verdict = Verdict(matches=True, causal_updates=[update])
    causal_memory.apply(turn, state, arrival, passages.index(arrival.content))
    current = state.causal_memory.actors["npc"][0]
    assert current.facts["cause"] == original.facts["cause"]
    assert current.facts["consequence"] == original.facts["consequence"]
    assert current.facts["event"].source.message_id == "arrival"
    assert current.closure is None
    assert state.agenda == [] and state.memories == {}
    assert all(
        source.facts is None and source.reported for source in state.minds["npc"].sources.values()
    )


def test_pinned_causal_quotes_reach_cognition_without_lexical_overlap_or_an_agent_call():
    _, state, _ = opened()
    mind = state.minds["npc"]
    pins = causal_memory.pins(mind, state.causal_memory.actors["npc"])
    window = appraisal_context.build(mind, query="Ну?", recall_limit=0, recent_limit=0, pinned=pins)
    assert [item["text"] for item in window.payload["visible_evidence"]] == [TEXT]
    assert window.payload["visible_evidence"][0]["kind"] == "reported"
    assert window.payload["visible_evidence"][0]["channel"] == "narration"


async def test_configured_agent_sees_causal_context_and_preserves_the_shared_source_budget(
    monkeypatch,
):
    _, state, _ = opened()
    mind = state.minds["npc"]
    threads = state.causal_memory.actors["npc"]
    pinned = causal_memory.pins(mind, threads)
    supplied = {"causal_continuity_not_world_facts": causal_memory.view(threads)}
    request = AsyncMock(return_value=Step(requests=[]))
    monkeypatch.setattr(inference, "request", request)
    tools, audit = await agent.investigate(
        SimpleNamespace(game_id="session"),
        Settings(mode="live", actor_ids=["npc"], agent_steps=1),
        Usage(),
        mind,
        observation(),
        supplied,
        pinned=pinned,
    )
    assert tools.pins == pinned and audit[0]["stop"] == "ready"
    assert (
        request.call_args.args[4]["causal_continuity_not_world_facts"]
        == supplied["causal_continuity_not_world_facts"]
    )
    assert request.await_count == 1


@pytest.mark.parametrize("case", ["session", "revision", "hash", "missing", "role"])
async def test_source_checks_prevent_stale_or_foreign_causal_facts(case):
    _, state, reply = opened()
    if case == "session":
        reply.session_id = "other-session"
    if case == "revision":
        reply.revision_id = "v2"
    if case == "hash":
        reply.content += " Changed."
    if case == "role":
        reply.role = "user"
    host = SimpleNamespace(
        game_id="session",
        db=SimpleNamespace(scalars=AsyncMock(return_value=[] if case == "missing" else [reply])),
    )
    assert await causal_memory.recall(host, state.causal_memory, {"npc"}) == {"npc": []}
    assert await causal_memory.recall(host, state.causal_memory, {"other"}) == {"other": []}


@pytest.mark.parametrize(
    "case", ["foreign", "fabricated", "unknown-thread", "bad-shape", "plans-only", "non-object"]
)
def test_invalid_optional_notes_leave_previous_causal_state_usable(case):
    turn, state, reply = opened()
    before = state.causal_memory.model_dump_json()
    body = draft()
    if case == "foreign":
        body["actor_id"] = "other"
    if case == "fabricated":
        body["facts"]["purpose"]["passage_id"] = "invented"
    if case == "unknown-thread":
        body.update(action="close", thread_id="invented")
    if case == "bad-shape":
        body["action"] = "forget-everything"
    if case == "plans-only":
        body["facts"] = {"purpose": body["facts"]["purpose"], "next_step": body["facts"]["cause"]}
    if case == "non-object":
        body = None
    turn.verdict = Verdict(matches=True, causal_updates=[body])
    causal_memory.apply(turn, state, reply, passages.index(TEXT))
    assert state.causal_memory.model_dump_json() == before
    assert len(state.usage.causal_notes) == 1 and turn.verdict.matches


def test_repeated_apply_is_idempotent_and_duplicate_purposes_do_not_fill_the_ledger():
    turn, state, reply = opened()
    before = state.model_dump_json()
    causal_memory.apply(turn, state, reply, passages.index(TEXT))
    assert state.model_dump_json() == before
    reply = source("repeated", TEXT)
    causal_memory.apply(turn, state, reply, passages.index(TEXT))
    assert len(state.causal_memory.actors["npc"]) == 1
    assert "duplicate" in state.usage.causal_notes[0]


def test_regeneration_retracts_causal_notes_and_fork_rebinds_only_complete_chains():
    _, state, _ = opened()
    states = {KEY: state.model_dump()}
    forked = lifecycle.fork(states, {"sample": "fork-sample"}, "fork")
    restored = KernelState.model_validate(forked[KEY])
    references = causal_memory.anchors(restored.causal_memory.actors["npc"][0])
    assert all(ref.session_id == "fork" and ref.message_id == "fork-sample" for ref in references)
    lifecycle.validate(forked, "fork")
    with pytest.raises(ValueError, match="another session"):
        lifecycle.validate(forked, "foreign")
    assert not lifecycle.fork(states, {}, "fork")[KEY]["causal_memory"]["actors"]["npc"]
    host = SimpleNamespace(entity_states=states)
    retract(host, "sample")
    assert load(host).causal_memory.actors["npc"] == []


def test_old_saves_have_empty_causal_memory_without_a_schema_version_bump():
    raw = KernelState().model_dump()
    raw.pop("causal_memory")
    raw["usage"].pop("causal_notes")
    restored = KernelState.model_validate(raw)
    assert restored.schema_version == 6
    assert restored.causal_memory == Memory()
    assert restored.usage.causal_notes == []


def test_settings_do_not_copy_completed_turn_causal_events_into_the_retry_baseline():
    _, state, _ = opened()
    original = KernelState().model_dump()
    replay = SimpleNamespace(before={"state": {"entity_states": {KEY: original}}})
    _update_replay(replay, state.model_dump())
    restored = KernelState.model_validate(replay.before["state"]["entity_states"][KEY])
    assert restored.causal_memory == Memory()
    assert state.causal_memory.actors["npc"]


async def test_fallback_preserves_concrete_causal_circumstances_without_model_calls(monkeypatch):
    _, state, reply = opened()
    host, actor = manager()
    state.settings = load(host.state).settings.model_copy(update={"failure_policy": "continue"})
    state.recovery.cooldown_remaining = 1
    host.state.entity_states[KEY] = state.model_dump()
    host.db = SimpleNamespace(scalars=AsyncMock(return_value=[reply]))
    monkeypatch.setattr(context, "available", lambda *_: True)
    request = AsyncMock(side_effect=AssertionError("No paid cooldown inference"))
    monkeypatch.setattr(inference, "request", request)
    prompt = await runtime.prepare(host, "An unrelated topic", [actor])
    assert "The sample is in Rin's inner coat pocket" in prompt
    assert runtime.current(host).simplified
    request.assert_not_awaited()
    assert load(host.state).causal_memory == state.causal_memory


def test_many_completed_threads_have_a_bounded_recent_view_and_keep_open_business():
    turn, state, reply = opened()
    initial = state.causal_memory.actors["npc"][0]
    for index in range(10):
        reply = source(f"new-{index}", TEXT)
        body = draft()
        body["facts"]["purpose"]["text"] = f"Analyse separate sample {index}"
        turn.verdict = Verdict(matches=True, causal_updates=[body])
        causal_memory.apply(turn, state, reply, passages.index(TEXT))
        target = next(
            thread
            for thread in state.causal_memory.actors["npc"]
            if thread.facts["purpose"].text == f"Analyse separate sample {index}"
        )
        done = source(f"done-{index}", "Rin completed the analysis.")
        body = {
            "actor_id": "npc",
            "action": "close",
            "thread_id": target.id,
            "facts": {"consequence": {"text": "The analysis is complete", "passage_id": "p0"}},
        }
        turn.verdict = Verdict(matches=True, causal_updates=[body])
        causal_memory.apply(turn, state, done, passages.index(done.content))
    threads = state.causal_memory.actors["npc"]
    assert len(threads) == 4
    assert threads[0] == initial and initial.closure is None
    assert sum(thread.closure is not None for thread in threads) == 3
    assert len(causal_memory.view(threads)) == 2
    assert any("recent view" in note for note in state.usage.causal_notes)


def test_unapproved_reply_cannot_create_causal_history():
    turn, state, reply = opened()
    before = state.model_dump_json()
    turn.verdict = Verdict(matches=False, causal_updates=[draft()])
    causal_memory.apply(turn, state, reply, passages.index(TEXT))
    assert state.model_dump_json() == before
    turn.verdict.matches = True
    reply.session_id = "foreign"
    with pytest.raises(ChpmError, match="another session"):
        causal_memory.apply(turn, state, reply, passages.index(TEXT))
