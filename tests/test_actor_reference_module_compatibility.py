"""Offline cross-module decisions, controller gates, scheduling and private-source boundaries."""

import asyncio
import json
from contextlib import asynccontextmanager
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from backend.core.inference.registry import background_call, concurrent_call
from backend.core.llm_router import GameMasterLLM
from backend.engine.chpm import inference as personality_inference
from backend.engine.chpm import runtime as personality_runtime
from backend.engine.chpm.errors import ChpmError
from backend.engine.chpm.notebook import NotebookWorkspace
from backend.engine.chpm.notebook_store import persist_workspace
from backend.engine.chpm.schema import KernelState
from backend.engine.chpm.schema import Settings as PersonalitySettings
from backend.engine.chpm.state import KEY
from backend.engine.chpm.template_settings import ensure_session_compatible
from backend.engine.living_world import (
    concordia_adapter,
    deliberation,
    orchestration,
    reference_recall,
    request_slot,
)
from backend.engine.living_world.decisions import Decision, PrivateNotes
from backend.engine.living_world.schema import Event
from backend.engine.living_world.state import load, save
from backend.engine.memory_rag import control, documents, recall_sources, scheduling, worker
from backend.engine.memory_rag.scheduling import IdleScheduler
from backend.models.adventure_template import AdventureTemplate
from backend.models.memory_rag import MemoryIndexState
from backend.models.session_state import SessionState
from tests.conftest import TestSessionLocal
from tests.test_chpm_host_state import mind
from tests.test_living_world_decisions import configure, fake, post, ready, world
from tests.test_living_world_reference_recall import knowledge

__all__ = ["ready", "world"]


@pytest.fixture(autouse=True)
def isolated_background_scheduler(monkeypatch):
    selected = IdleScheduler(grace_seconds=0)
    for module in (request_slot, scheduling, worker):
        monkeypatch.setattr(module, "scheduler", selected)


async def _state(db):
    return await db.scalar(select(SessionState).where(SessionState.session_id == "session-1"))


async def _index(db):
    return await db.scalar(
        select(MemoryIndexState).where(MemoryIndexState.session_id == "session-1")
    )


@pytest.mark.parametrize("engine", ["native", "concordia"])
async def test_restored_live_personality_and_living_world_cannot_execute_two_controllers(
    ready, monkeypatch, engine
):
    if engine == "concordia" and not concordia_adapter.available():
        pytest.skip("Optional Concordia extra is not installed.")
    await configure(ready, deliberation_enabled=True, mode="CATCH_UP", decision_engine=engine)
    async with TestSessionLocal() as db:
        state = await _state(db)
        adventure = await db.get(AdventureTemplate, state.template_id)
        adventure.rule_enforcement_mode, adventure.strict_rules = "vn", False
        state.entity_states = {
            **state.entity_states,
            KEY: KernelState(
                settings=PersonalitySettings(mode="live", actor_ids=["LILI"])
            ).model_dump(mode="json"),
        }
        await db.commit()
    captured = fake(monkeypatch)
    response = await post(ready)
    assert response.status_code == 409, response.text
    assert captured == []


@pytest.mark.parametrize("busy", ["foreground", "maintenance"])
async def test_actor_query_obeys_existing_background_priority_before_model_admission(
    ready, monkeypatch, busy
):
    await knowledge(index=True)
    async with TestSessionLocal() as db:
        state, index = await _state(db), await _index(db)
        index.template_id = state.template_id
        await db.commit()
    entered = asyncio.Event()
    priorities = []

    async def embed(*args, **kwargs):
        priorities.append(background_call.get())
        entered.set()
        return [[1.0, 0.0]]

    monkeypatch.setattr(reference_recall, "embed_texts", embed)
    monkeypatch.setattr(reference_recall.LanceMemoryStore, "query", AsyncMock(return_value=[]))
    captured = fake(monkeypatch)
    occupied = (
        scheduling.scheduler.foreground if busy == "foreground" else worker.scheduler.background
    )
    async with occupied():
        task = asyncio.create_task(post(ready))
        try:
            await asyncio.wait_for(entered.wait(), 0.2)
            submitted_while_foreground = True
        except TimeoutError:
            submitted_while_foreground = False
    response = await asyncio.wait_for(task, 5)
    assert response.status_code == 200, response.text
    assert not submitted_while_foreground, "Reference embeddings must preserve foreground priority."
    assert priorities == [True]
    assert len(captured) == 1


async def test_restored_controller_conflict_also_blocks_personality_before_inference(
    ready, monkeypatch
):
    async with TestSessionLocal() as db:
        state = await _state(db)
        adventure = await db.get(AdventureTemplate, state.template_id)
        adventure.rule_enforcement_mode, adventure.strict_rules = "vn", False
        state.entity_states = {
            **state.entity_states,
            KEY: KernelState(
                settings=PersonalitySettings(mode="live", actor_ids=["LILI"])
            ).model_dump(mode="json"),
        }
        await db.commit()
        original = deepcopy(state.entity_states)
        request = AsyncMock(
            side_effect=AssertionError("Conflicting controllers cannot request inference.")
        )
        monkeypatch.setattr(personality_inference, "request", request)
        manager = SimpleNamespace(state=state, adventure=adventure, game_id="session-1")
        with pytest.raises(ChpmError, match="Disable Living World"):
            await personality_runtime.prepare(manager, "I wait.", [])
        assert state.entity_states == original
        request.assert_not_awaited()


@pytest.mark.parametrize("concurrent", [False, True])
@pytest.mark.parametrize("engine", ["native", "concordia"])
async def test_query_and_generation_share_one_admission_and_keep_opt_in_overlap(
    ready, monkeypatch, concurrent, engine
):
    if engine == "concordia" and not concordia_adapter.available():
        pytest.skip("Optional Concordia extra is not installed.")
    await knowledge(index=True)
    await configure(
        ready,
        deliberation_enabled=True,
        mode="CATCH_UP",
        allow_concurrent_requests=concurrent,
        decision_engine=engine,
    )
    async with TestSessionLocal() as db:
        state, index = await _state(db), await _index(db)
        index.template_id = state.template_id
        await db.commit()
    admissions, policies = [], []
    original_slot = orchestration.decision_slot

    @asynccontextmanager
    async def admission(overlap):
        admissions.append(overlap)
        async with original_slot(overlap):
            yield

    @asynccontextmanager
    async def nested_slot(_overlap):
        pytest.fail("The admitted utility request attempted a second scheduler reservation.")
        yield

    async def embed(*args, **kwargs):
        policies.append(("query", background_call.get(), concurrent_call.get()))
        return [[1.0, 0.0]]

    async def generate(self, instruction, payload, model, **kwargs):
        policies.append(("generation", background_call.get(), concurrent_call.get()))
        return Decision(action="WAIT", goal="Wait.", belief="Unsure.").model_dump_json()

    monkeypatch.setattr(orchestration, "decision_slot", admission)
    monkeypatch.setattr(deliberation, "decision_slot", nested_slot)
    monkeypatch.setattr(reference_recall, "embed_texts", embed)
    monkeypatch.setattr(reference_recall.LanceMemoryStore, "query", AsyncMock(return_value=[]))
    monkeypatch.setattr(GameMasterLLM, "aexecute_simple_task", generate)
    if concurrent:
        async with request_slot.scheduler.foreground():
            response = await asyncio.wait_for(post(ready), 5)
    else:
        response = await asyncio.wait_for(post(ready), 5)
    assert response.status_code == 200, response.text
    assert admissions == [concurrent]
    assert policies == [("query", True, concurrent), ("generation", True, concurrent)]
    assert response.json()["llm_calls"] == 1


async def test_stop_cancels_admission_before_any_reference_or_generation_call(ready, monkeypatch):
    await knowledge(index=True)
    queued = asyncio.Event()
    original_slot = orchestration.decision_slot

    @asynccontextmanager
    async def admission(overlap):
        queued.set()
        async with original_slot(overlap):
            yield

    monkeypatch.setattr(orchestration, "decision_slot", admission)
    retrieve = AsyncMock(side_effect=AssertionError("The stopped request was still queued."))
    monkeypatch.setattr(reference_recall, "retrieve", retrieve)
    captured = fake(monkeypatch)
    async with request_slot.scheduler.foreground():
        task = asyncio.create_task(post(ready))
        await asyncio.wait_for(queued.wait(), 5)
        assert (await ready.post("/api/adventures/session-1/living-world/stop")).status_code == 200
        response = await asyncio.wait_for(task, 5)
    assert response.status_code == 409 and captured == []
    retrieve.assert_not_awaited()


async def test_direct_infer_keeps_its_default_admission_wrapper(ready, monkeypatch):
    admissions = []

    @asynccontextmanager
    async def admission(overlap):
        admissions.append(overlap)
        yield

    result = Decision(action="WAIT", goal="Wait.", belief="Unsure.")
    llm = SimpleNamespace(
        max_tokens=4096,
        enable_thinking=True,
        model="fixture",
        aexecute_simple_task=AsyncMock(return_value=result.model_dump_json()),
    )
    prepared = deliberation.Prepared("event", "fence", {}, 256, "native")
    monkeypatch.setattr(deliberation, "decision_slot", admission)
    assert await deliberation.infer(llm, prepared, "session-1") == result
    assert admissions == [False] and llm.max_tokens == 256 and not llm.enable_thinking
    llm.aexecute_simple_task.assert_awaited_once()


def test_controller_guard_does_not_replay_an_unrelated_disabled_living_world_ledger():
    state = SimpleNamespace(
        entity_states={},
        living_world={"settings": {"deliberation_enabled": False}, "events": "unrelated-ledger"},
    )
    ensure_session_compatible(state, PersonalitySettings(mode="live", actor_ids=["LILI"]))


async def test_notebooks_and_private_simulation_data_never_enter_either_public_rag_corpus(ready):
    owner, _ = await knowledge()
    async with TestSessionLocal() as db:
        state = await _state(db)
        simulation = load(state)
        simulation.private_notes["LILI"] = PrivateNotes(
            goal="private-goal-sentinel", belief="private-belief-sentinel"
        )
        simulation.events.insert(
            0,
            Event(
                event_id="private-event",
                due=0,
                kind="SOCIAL",
                actor="LILI",
                participant="MIRINDA",
                status="COMMITTED",
                result="private-event-sentinel",
            ),
        )
        save(state, simulation)
        state.world_memories = [
            {"id": "existing-memory", "description": "existing-consequence-sentinel"}
        ]
        workspace = NotebookWorkspace()
        workspace.write("", '{"private":"notebook-sentinel"}', expected_revision=0)
        await persist_workspace(db, mind("LILI", "session-1"), workspace, owner_id=owner)
        await db.commit()
        full = await documents.collect_documents(db, state, owner)
        foreground = await recall_sources.collect_documents(db, state, owner, query="sentinel")
        for corpus in (full, foreground):
            body = " ".join(document.text for document in corpus)
            assert "existing-consequence-sentinel" in body
            assert all(
                marker not in body
                for marker in (
                    "private-goal-sentinel",
                    "private-belief-sentinel",
                    "private-event-sentinel",
                    "notebook-sentinel",
                )
            )
            assert len([document for document in corpus if document.layer == "world_memory"]) == 1


@pytest.mark.parametrize("engine", ["native", "concordia"])
@pytest.mark.parametrize("recall_mode", ["disabled", "paused", "outage"])
async def test_reference_modes_preserve_cycle_dependencies_clock_and_actor_isolation(
    ready, monkeypatch, engine, recall_mode
):
    if engine == "concordia" and not concordia_adapter.available():
        pytest.skip("Optional Concordia extra is not installed.")
    await knowledge(index=True, enabled=recall_mode != "disabled")
    await configure(
        ready,
        deliberation_enabled=True,
        mode="CATCH_UP",
        decision_engine=engine,
        max_decisions_per_run=2,
        max_events=4,
    )
    async with TestSessionLocal() as db:
        state, index = await _state(db), await _index(db)
        index.template_id, index.paused = state.template_id, recall_mode == "paused"
        simulation = load(state)
        simulation.events = [
            Event(event_id="prerequisite", due=5, kind="WAIT"),
            Event(
                event_id="first",
                due=10,
                kind="DECISION",
                actor="LILI",
                dependencies=["prerequisite"],
            ),
            Event(
                event_id="second",
                due=11,
                kind="SOCIAL",
                actor="MIRINDA",
                participant="LILI",
                dependencies=["first"],
            ),
        ]
        save(state, simulation)
        await db.commit()
    embed = AsyncMock(side_effect=RuntimeError("Controlled optional embedding outage"))
    monkeypatch.setattr(reference_recall, "embed_texts", embed)
    supplied = []

    async def generate(self, instruction, payload, model, **kwargs):
        context = json.loads(payload)
        supplied.append(context)
        return Decision(
            action="WAIT",
            goal="private-LILI-goal" if len(supplied) == 1 else "Wait.",
            belief="Uncertain.",
        ).model_dump_json()

    monkeypatch.setattr(GameMasterLLM, "aexecute_simple_task", generate)
    response = await post(ready, "/cycle")
    assert response.status_code == 200, response.text
    assert [context["actor"]["id"] for context in supplied] == ["LILI", "MIRINDA"]
    assert ("reference_recall" in supplied[0]) == (recall_mode != "disabled")
    assert "reference_recall" not in supplied[1]
    assert "private-LILI-goal" not in json.dumps(supplied[1])
    assert embed.await_count == (1 if recall_mode == "outage" else 0)
    async with TestSessionLocal() as db:
        state = await _state(db)
        simulation = load(state)
        assert all(event.status == "COMMITTED" for event in simulation.events)
        assert [event.committed_at for event in simulation.events] == [5, 10, 11]
        assert state.in_game_time == simulation.cursor == simulation.target == 60
    assert response.json()["llm_calls"] == len(supplied) == 2


async def test_pause_index_during_decision_rejects_snapshot_and_retry_uses_sql(ready, monkeypatch):
    await knowledge(index=True)
    async with TestSessionLocal() as db:
        state, index = await _state(db), await _index(db)
        index.template_id = state.template_id
        await db.commit()
    monkeypatch.setattr(reference_recall, "_vectors", AsyncMock(return_value=[]))

    async def generate(self, instruction, supplied, model, **kwargs):
        assert "silver treaty is kept" in json.loads(supplied)["reference_recall"]
        async with TestSessionLocal() as writer:
            await control.invalidate(writer, await _index(writer), paused=True)
            await writer.commit()
        return Decision(action="WAIT", goal="Wait.", belief="Unsure.").model_dump_json()

    monkeypatch.setattr(GameMasterLLM, "aexecute_simple_task", generate)
    rejected = await post(ready)
    assert rejected.status_code == 409, rejected.text
    captured = fake(monkeypatch)
    retry = await post(ready)
    assert retry.status_code == 200, retry.text
    assert "silver treaty is kept" in captured[0]["reference_recall"]
