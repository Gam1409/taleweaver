"""Two NPCs move, speak and retain distinct private beliefs across lifecycle operations."""

import asyncio
import json

import pytest
from sqlalchemy import select

from backend.core.llm_router import GameMasterLLM
from backend.engine.living_world import concordia_adapter
from backend.engine.living_world.decisions import Decision
from backend.engine.living_world.schema import Event
from backend.engine.living_world.state import load, save
from backend.engine.memory_rag.documents import collect_documents
from backend.engine.session_checkpoint_service import SessionCheckpointService
from backend.engine.session_exporter import SessionExporter
from backend.models.session_state import SessionState
from tests import test_living_world_decisions as helpers
from tests.conftest import TestSessionLocal

ready, world = helpers.ready, helpers.world


@pytest.mark.parametrize("engine", ["native", "concordia"])
async def test_two_npc_acceptance_and_checkpoint_rewind(ready, monkeypatch, engine):
    if engine == "concordia" and not concordia_adapter.available():
        pytest.skip("Optional Concordia extra is not installed.")
    await helpers.configure(
        ready,
        mode="CATCH_UP",
        deliberation_enabled=True,
        decision_engine=engine,
        max_decisions_per_run=4,
    )
    async with TestSessionLocal() as db:
        state = await db.scalar(select(SessionState).where(SessionState.session_id == "session-1"))
        sim = load(state)
        sim.events = [
            Event(event_id="lili-move", due=10, kind="DECISION", actor="LILI"),
            Event(event_id="mirinda-move", due=10, kind="DECISION", actor="MIRINDA"),
            Event(
                event_id="question",
                due=11,
                kind="SOCIAL",
                actor="LILI",
                participant="MIRINDA",
                dependencies=["lili-move", "mirinda-move"],
            ),
            Event(
                event_id="answer",
                due=12,
                kind="SOCIAL",
                actor="MIRINDA",
                participant="LILI",
                dependencies=["question"],
            ),
        ]
        save(state, sim)
        await db.commit()
        checkpoint = await SessionCheckpointService.create_checkpoint(db, "session-1", "MANUAL")
        await db.commit()
        checkpoint_id = checkpoint.id
    contexts = []

    async def generate(self, system, user, model, **kwargs):
        context = json.loads(user)
        contexts.append(context)
        actor = context["actor"]["id"]
        if context["event_kind"] == "DECISION":
            return Decision(
                action="MOVE",
                destination="ROOM",
                goal=f"{actor} wants a quiet meeting.",
                belief=f"{actor} expects privacy.",
            ).model_dump_json()
        return Decision(
            action="TALK",
            participant=context["participants"][0]["id"],
            speech="Is the hall empty?" if actor == "LILI" else "I think it is.",
            goal=f"{actor} has an independent goal.",
            belief=f"{actor} might be mistaken.",
        ).model_dump_json()

    monkeypatch.setattr(GameMasterLLM, "aexecute_simple_task", generate)
    response = await helpers.post(ready, "/cycle")
    assert response.status_code == 200, response.text
    assert len(contexts) == 4 and response.json()["status"] == "COMPLETE"
    assert contexts[2]["scene"]["id"] == contexts[3]["scene"]["id"] == "ROOM"
    assert "Is the hall empty?" in " ".join(contexts[3]["observations"])
    assert "LILI expects privacy" not in json.dumps(contexts[3]["private_notes"])
    async with TestSessionLocal() as db:
        state = await db.scalar(select(SessionState).where(SessionState.session_id == "session-1"))
        final = load(state)
        assert all(item.status == "COMMITTED" for item in final.events)
        assert final.private_notes["LILI"].belief != final.private_notes["MIRINDA"].belief
        exported = await SessionExporter.build_session_manifest(db, "session-1")
        assert exported["session_state"]["living_world"]["private_notes"]
        documents = await collect_documents(db, state, state.user_id)
        assert "independent goal" not in str(documents) and "might be mistaken" not in str(
            documents
        )
        await SessionCheckpointService.restore_checkpoint(db, "session-1", checkpoint_id)
        await db.commit()
        await db.refresh(state)
        restored = load(state)
        assert restored.timeline != final.timeline and not restored.private_notes
        assert all(item.status == "PLANNED" for item in restored.events)
        assert (state.entity_states or {}).get("LILI", {}).get(
            "current_scene_id", "START"
        ) == "START"


async def test_stop_discards_cancellation_resistant_model_reply(ready, monkeypatch):
    entered, release, finished = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def generate(*args, **kwargs):
        entered.set()
        try:
            await release.wait()
        except asyncio.CancelledError:
            await release.wait()
        finished.set()
        return Decision(
            action="MOVE", destination="ROOM", goal="Late.", belief="Late."
        ).model_dump_json()

    monkeypatch.setattr(GameMasterLLM, "aexecute_simple_task", generate)
    task = asyncio.create_task(helpers.post(ready))
    await asyncio.wait_for(entered.wait(), 5)
    try:
        await ready.post(helpers.BASE + "/stop")
        response = await asyncio.wait_for(task, 5)
        assert response.status_code == 409
    finally:
        release.set()
    await asyncio.wait_for(finished.wait(), 5)
    journal = (await ready.get(helpers.BASE + "/events")).json()
    assert not journal["private_notes"] and journal["events"][0]["status"] == "WAITING_FOR_LLM"


async def test_stop_during_final_validation_cannot_commit(ready, monkeypatch):
    from backend.engine.living_world import deliberation

    helpers.fake(monkeypatch, action="MOVE", destination="ROOM")
    original = deliberation.context_for
    reached, release = asyncio.Event(), asyncio.Event()
    calls = 0

    async def gated(*args, **kwargs):
        nonlocal calls
        context = await original(*args, **kwargs)
        calls += 1
        if calls == 2:
            reached.set()
            await release.wait()
        return context

    monkeypatch.setattr(deliberation, "context_for", gated)
    task = asyncio.create_task(helpers.post(ready))
    await asyncio.wait_for(reached.wait(), 5)
    try:
        assert (await ready.post(helpers.BASE + "/stop")).json()["stop_requested"]
    finally:
        release.set()
    assert (await task).status_code == 409
    journal = (await ready.get(helpers.BASE + "/events")).json()
    assert journal["events"][0]["status"] == "WAITING_FOR_LLM" and not journal["private_notes"]


async def test_unavailable_concordia_never_silently_falls_back(ready, monkeypatch):
    captured = helpers.fake(monkeypatch)
    monkeypatch.setattr(concordia_adapter, "available", lambda: False)
    await helpers.configure(
        ready, mode="CATCH_UP", deliberation_enabled=True, decision_engine="concordia"
    )
    response = await helpers.post(ready)
    assert response.status_code == 409 and captured == []
    assert (await ready.get(helpers.BASE)).json()["llm_calls"] == 0


@pytest.mark.parametrize(
    "proposal",
    [
        {"action": "MOVE", "destination": "NONEXISTENT"},
        {"action": "TALK", "participant": "MISSING", "speech": "Hello."},
    ],
)
async def test_unavailable_action_cannot_create_world_facts(ready, monkeypatch, proposal):
    helpers.fake(monkeypatch, **proposal)
    response = await helpers.post(ready)
    assert response.status_code == 422
    journal = (await ready.get(helpers.BASE + "/events")).json()
    assert not journal["private_notes"]
    assert journal["events"][0]["status"] == "WAITING_FOR_LLM"
    assert journal["events"][0]["result"] == ""


async def test_global_model_timeout_bounds_the_whole_decision(ready, monkeypatch):
    original = GameMasterLLM.for_role
    reached = asyncio.Event()

    def router(*args, **kwargs):
        llm = original(*args, **kwargs)
        llm.request_timeout = 0.05
        return llm

    async def generate(*args, **kwargs):
        reached.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(GameMasterLLM, "for_role", router)
    monkeypatch.setattr(GameMasterLLM, "aexecute_simple_task", generate)
    response = await asyncio.wait_for(helpers.post(ready), 5)
    assert response.status_code == 504
    assert reached.is_set()
    journal = (await ready.get(helpers.BASE + "/events")).json()
    assert not journal["private_notes"] and journal["events"][0]["attempts"] == 1


async def test_event_budget_is_shared_across_rules_and_model_steps(ready, monkeypatch):
    captured = helpers.fake(monkeypatch)
    await helpers.configure(
        ready,
        mode="CATCH_UP",
        deliberation_enabled=True,
        auto_schedule=True,
        max_events=1,
        max_decisions_per_run=4,
    )
    response = await helpers.post(ready, "/cycle")
    assert response.status_code == 200, response.text
    assert len(captured) == 1
    assert response.json()["last_run_events"] == 1
    assert response.json()["pending_events"] > 0
