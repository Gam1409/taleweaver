"""A declared multi-day skip preserves bounded world backlog and real Concordia actions."""

import json

import pytest
from sqlalchemy import select

from backend.api.routes.adventures.gameplay_logic import GameTurnManager
from backend.core.config import settings
from backend.core.llm_router import GameMasterLLM
from backend.engine.living_world import concordia_adapter
from backend.engine.living_world.decisions import Decision
from backend.engine.living_world.runner import Budget, run
from backend.engine.living_world.schema import Event, Settings, Simulation
from backend.engine.living_world.state import load, reconcile, save
from backend.engine.memory_rag.scheduling import scheduler
from backend.models.adventure_template import AdventureTemplate
from backend.models.session_state import SessionState
from backend.models.user import User
from backend.models.world_entity import WorldScene
from tests import test_living_world_api as api
from tests.conftest import TestSessionLocal
from tests.test_vn_time_passage import PassageRoles
from tests.test_vn_turn_integration import final_payload, install_roles

world = api.world


async def advance_story(engine, request, target):
    async with TestSessionLocal() as db:
        state = await db.scalar(select(SessionState).where(SessionState.session_id == "session-1"))
        user = await db.get(User, state.user_id)
        user.llm_settings = {"small_model_provider": "ollama", "small_model": "test"}
        template = await db.get(AdventureTemplate, state.template_id)
        template.rule_enforcement_mode = "vn"
        template.strict_rules = False
        state.enable_history_compression = False
        db.add(
            WorldScene(
                session_id="session-1", id="LOUNGE", label="Lounge", description="A quiet lounge."
            )
        )
        state.current_scene_id = "LOUNGE"  # The two residents are outside the player's scene.
        save(
            state,
            Simulation(
                settings=Settings(
                    living_world_enabled=True,
                    mode="CATCH_UP",
                    deliberation_enabled=True,
                    decision_engine=engine,
                    max_catchup_game_hours=6,
                    max_decisions_per_run=1,
                ),
                events=[
                    Event(event_id="lili", due=60, kind="DECISION", actor="LILI"),
                    Event(event_id="mirinda", due=400, kind="DECISION", actor="MIRINDA"),
                ],
            ),
        )
        await db.commit()
        events = [
            item async for item in GameTurnManager(db, "session-1", user).process_turn(request)
        ]
        assert final_payload(events)["status"] == "success", "".join(events)
        assert final_payload(events)["sheet"]["in_game_time"] == target
        assert state.in_game_time == target


@pytest.mark.asyncio
@pytest.mark.parametrize("engine", ["native", "concordia"])
@pytest.mark.parametrize("days", [3, 30, 90, 180])
async def test_long_passage_keeps_clock_and_pending_npc_moves_until_world_catches_up(
    world, monkeypatch, engine, days
):
    if engine == "concordia" and not concordia_adapter.available():
        pytest.skip("Optional Concordia extra is not installed.")
    monkeypatch.setattr(settings, "INFERENCE_SERIALIZATION_ENABLED", True)
    monkeypatch.setattr(scheduler, "grace_seconds", 0)
    request, target = f"Прошло {days} дней.", days * 1440
    roles = PassageRoles(request, amount=days)
    install_roles(monkeypatch, roles)
    monkeypatch.setattr("tests.test_vn_turn_integration.NARRATION", request)
    await advance_story(engine, request, target)
    contexts = []

    async def decide(self, system, content, model, **kwargs):
        contexts.append(json.loads(content))
        return Decision(
            action="MOVE",
            destination="ROOM",
            goal="Find a quiet place.",
            belief="The room may be quiet.",
        ).model_dump_json()

    monkeypatch.setattr(GameMasterLLM, "aexecute_simple_task", decide)

    async def cycle():
        revision = (await world.get(api.BASE)).json()["revision"]
        result = await world.post(api.BASE + "/cycle", json={"expected_revision": revision})
        assert result.status_code == 200, result.text
        return result.json()

    first = await cycle()
    assert len(contexts) == 1 and contexts[0]["minute"] == 60
    assert first["target"] == target and first["cursor"] <= 360
    assert first["status"] == "PARTIAL" and first["pending_events"] == 1
    async with TestSessionLocal() as db:
        state = await db.scalar(select(SessionState).where(SessionState.session_id == "session-1"))
        assert state.in_game_time == target  # World catch-up must not rewind the story clock.
        assert state.entity_states["LILI"]["current_scene_id"] == "ROOM"
        assert (state.entity_states.get("MIRINDA") or {}).get(
            "current_scene_id", "START"
        ) == "START"
    result = await cycle()
    if result["status"] != "COMPLETE":
        result = await cycle()
    assert result["status"] == "COMPLETE" and result["cursor"] == result["target"] == target
    assert len(contexts) == 2 and contexts[1]["minute"] == 400
    async with TestSessionLocal() as db:
        state = await db.scalar(select(SessionState).where(SessionState.session_id == "session-1"))
        assert state.in_game_time == target
        assert state.entity_states["MIRINDA"]["current_scene_id"] == "ROOM"
        assert all(event.status == "COMMITTED" for event in load(state).events)
    await cycle()
    assert len(contexts) == 2  # Repeated batches do not repeat decisions or moves.


@pytest.mark.asyncio
async def test_shared_cycle_budget_never_rewinds_a_reconciled_empty_interval(world):
    async with TestSessionLocal() as db:
        state = await db.scalar(select(SessionState).where(SessionState.session_id == "session-1"))
        state.in_game_time = 4320
        simulation = Simulation(
            settings=Settings(living_world_enabled=True, mode="CATCH_UP"),
            cursor=60,
            target=4320,
            events=[Event(event_id="done", due=60, kind="WAIT", status="COMMITTED")],
        )
        budget = Budget(game_limit=360, events_left=15, seconds_left=2)
        reconcile(simulation, state.in_game_time, None)
        assert simulation.cursor == 4320
        await run(db, state, simulation, budget=budget)
        assert simulation.cursor == state.in_game_time == 4320
        assert simulation.status == "COMPLETE" and budget.processed == 0
