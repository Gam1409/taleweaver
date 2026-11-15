"""Latest-turn replay retains explicit controller controls while rewinding world facts."""

from copy import deepcopy

import pytest

from backend.engine.chpm.schema import KernelState, Settings
from backend.engine.chpm.state import KEY
from backend.engine.chpm.template_settings import ensure_session_compatible
from backend.engine.living_world.schema import Settings as WorldSettings
from backend.engine.living_world.schema import Simulation
from backend.engine.living_world.state import load, save
from backend.engine.turn_replay.snapshot import with_current_controls
from backend.engine.turn_replay.undo import undo_latest
from backend.models.game_session import GameSession
from backend.models.session_state import SessionState
from backend.models.turn_replay import TurnReplay
from tests.conftest import TestSessionLocal
from tests.test_turn_replay import GameTurnManager, complete, fake_cycle, seed


@pytest.mark.parametrize("action", ["replay", "undo"])
async def test_existing_snapshot_does_not_reactivate_a_disabled_private_controller(
    monkeypatch, action
):
    async def checked_cycle(manager, *args, **kwargs):
        ensure_session_compatible(manager.state)
        async for event in fake_cycle(manager, *args, **kwargs):
            yield event

    monkeypatch.setattr(GameTurnManager, "_run_llm_cycle", checked_cycle)
    async with TestSessionLocal() as db:
        user, _, state = await seed(db)
        simulation = Simulation(
            settings=WorldSettings(living_world_enabled=True, deliberation_enabled=True)
        )
        save(state, simulation)
        await db.commit()
        message_id = await complete(db, user)
        await db.refresh(state)
        simulation = load(state)
        simulation.settings.living_world_enabled = False
        save(state, simulation)
        current = KernelState(settings=Settings(mode="live", actor_ids=["NPC"]))
        state.entity_states = {**(state.entity_states or {}), KEY: current.model_dump()}
        row = await db.get(TurnReplay, "session-1")
        before = deepcopy(row.before)
        before["state"]["entity_states"] = {
            **before["state"]["entity_states"],
            KEY: current.model_dump(),
        }
        row.before = before
        assert row.before["state"]["living_world"]["settings"]["living_world_enabled"] is True
        await db.commit()

        if action == "undo":
            game = await db.get(GameSession, "session-1")
            await undo_latest(db, game, message_id)
            await db.commit()
        else:
            manager = GameTurnManager(db, "session-1", user)
            chunks = [
                chunk
                async for chunk in manager.process_turn("ignored", replay_message_id=message_id)
            ]
            assert any(chunk.startswith("event: final") for chunk in chunks), chunks

        restored = await db.get(SessionState, state.id, populate_existing=True)
        assert load(restored).settings.living_world_enabled is False
        assert load(restored).settings.deliberation_enabled is True
        ensure_session_compatible(restored)
        assert restored.in_game_time == (0 if action == "undo" else 5)


@pytest.mark.parametrize("before_world", [False, True])
@pytest.mark.parametrize("current_world", [False, True])
def test_controls_projection_retains_only_historical_world_data(before_world, current_world):
    from backend.engine.living_world.schema import Event

    historical = Simulation(
        cursor=10,
        target=10,
        events=[Event(event_id="old-plan", due=15, kind="WAIT")],
    ).model_dump(mode="json")
    current = Simulation(
        cursor=50,
        target=60,
        settings=WorldSettings(living_world_enabled=False, deliberation_enabled=True),
        events=[Event(event_id="future-plan", due=60, kind="WAIT")],
    ).model_dump(mode="json")
    snapshot = {
        "state": {
            "in_game_time": 10,
            "is_debug_enabled": False,
            "living_world": historical if before_world else None,
            "entity_states": {"retained": "historical facts"},
        },
        "tables": {"unchanged": []},
    }
    original = deepcopy(snapshot)
    current_before = deepcopy(current)

    result = with_current_controls(
        snapshot, debug_enabled=True, living_world=current if current_world else None
    )

    assert snapshot == original and current == current_before
    assert result["state"]["is_debug_enabled"] is True
    assert result["state"]["entity_states"] == original["state"]["entity_states"]
    if not before_world and not current_world:
        assert result["state"]["living_world"] is None
        return
    world = result["state"]["living_world"]
    assert world["cursor"] == world["target"] == 10
    assert world["events"] == (historical["events"] if before_world else [])
    assert world["settings"]["living_world_enabled"] is False
    assert world["settings"]["deliberation_enabled"] is current_world
