"""Production command binding uses the real early initiative and recovery owners."""

import asyncio
import json
from copy import deepcopy

import pytest
from sqlalchemy import select

from backend.engine.chpm import performance
from backend.engine.chpm.schema import KernelState
from backend.engine.chpm.state import KEY, load
from backend.engine.npc_actions.combat_binding import bind
from backend.models.avatar import Avatar
from backend.models.session_state import SessionState
from backend.models.turn_replay import TurnReplay
from tests.combat_boundary_support import combat_world, deterministic_randint
from tests.test_npc_ability_choices import ability
from tests.test_npc_ability_port import ScriptModel, call, settings, turn

__all__ = ["combat_world"]


def npc_first(participants):
    ordered = sorted(participants, key=lambda row: row["id"] != "GUARD")
    return [{**row, "total": 20 - index} for index, row in enumerate(ordered)]


async def configured(world, monkeypatch, model, protocol="native", authored=True):
    world.state.entity_states = {
        **world.state.entity_states,
        KEY: KernelState(settings=settings(protocol)).model_dump(mode="json"),
    }
    if authored:
        world.npc.metadata_json = {**world.npc.metadata_json, "special_actions": [ability()]}
    await world.db.commit()
    world.manager._chpm_model_factory = lambda _role: model
    monkeypatch.setattr("backend.engine.gameplay.combat.rounds.roll_initiative", npc_first)
    monkeypatch.setattr(
        "backend.engine.combat.special_attacks.random.randint", deterministic_randint
    )


async def run(world, command):
    return [chunk async for chunk in world.manager.process_turn(command)]


async def saved(world):
    state = await world.db.scalar(
        select(SessionState)
        .where(SessionState.session_id == world.manager.game_id)
        .execution_options(populate_existing=True)
    )
    avatar = await world.db.get(Avatar, state.avatar_id, populate_existing=True)
    recovery = await world.db.get(TurnReplay, world.manager.game_id, populate_existing=True)
    return state, avatar, recovery


def final(events):
    chunk = next(chunk for chunk in events if chunk.startswith("event: final\n"))
    return json.loads(chunk.split("data: ", 1)[1])


@pytest.mark.parametrize("protocol", ["native", "json"])
async def test_process_turn_binds_model_before_first_existing_initiative(
    combat_world, monkeypatch, protocol
):
    world = combat_world
    model = ScriptModel(turn(call()))
    requested, telemetry = model.next, []

    def request_after_commit(data):
        assert world.manager._recoverable_turn and not world.db.in_transaction()
        return requested(data)

    monkeypatch.setattr(model, "next", request_after_commit)
    monkeypatch.setattr(
        "backend.engine.npc_actions.combat_binding.log_structured_event",
        lambda event, **fields: telemetry.append((event, fields)),
    )
    await configured(world, monkeypatch, model, protocol)
    events = await run(world, "/fight GUARD")
    assert not any(chunk.startswith("event: error") for chunk in events)
    combat = final(events)["combat"]
    assert len(model.calls) == 1
    assert combat["turn_index"] == 1 and combat["turn"] == "player"
    assert combat["enemies"][0]["mana"] == 93
    assert len([row for row in combat["log"] if row["type"] == "enemy_action"]) == 1
    state, avatar, recovery = await saved(world)
    assert avatar.hp == 99 and state.entity_states["GUARD"]["mana"] == 93
    assert recovery.status == "command_complete" and recovery.before["avatar"]["hp"] == 100
    usage = load(state).usage
    assert usage.status == "validated" and usage.calls == 1
    assert usage.timings[0].actor_id == "GUARD" and usage.timings[0].phase == "rpg_ability"
    assert telemetry[0][0] == "npc.combat.selection"
    assert telemetry[0][1]["actor_id"] == "GUARD"
    assert telemetry[0][1]["usage"]["timings"][0]["actor_id"] == "GUARD"
    assert performance.actor_id.get() == ""
    assert not load(state).actors and not load(state).minds


@pytest.mark.parametrize("protocol", ["native", "json"])
async def test_next_command_gets_fresh_frame_and_one_new_action(
    combat_world, monkeypatch, protocol
):
    world = combat_world
    model = ScriptModel(turn(call()), turn(call(identifier="call_2")))
    await configured(world, monkeypatch, model, protocol)
    await run(world, "/fight GUARD")
    first = world.manager._npc_ability_usage
    events = await run(world, "/rest")
    combat = final(events)["combat"]
    assert combat["round"] == 2 and combat["turn_index"] == 1
    assert combat["enemies"][0]["mana"] == 86
    assert len([row for row in combat["log"] if row["type"] == "enemy_action"]) == 2
    state, avatar, recovery = await saved(world)
    assert avatar.hp == 98 and recovery.status == "command_complete"
    assert world.manager._npc_ability_usage is not first
    assert load(state).usage.calls == 1 and len(model.calls) == 2


@pytest.mark.parametrize("protocol", ["native", "json"])
async def test_transport_failure_recovers_real_command_without_spending_cost(
    combat_world, monkeypatch, protocol
):
    world = combat_world
    model = ScriptModel(TimeoutError())
    await configured(world, monkeypatch, model, protocol)
    before = deepcopy(world.state.entity_states)
    events = await run(world, "/fight GUARD")
    assert any(chunk.startswith("event: error") for chunk in events)
    assert not any(chunk.startswith("event: final") for chunk in events)
    state, avatar, recovery = await saved(world)
    assert state.entity_states == before and avatar.hp == 100
    assert recovery.status == "pending" and recovery.backup is None
    assert world.manager._npc_ability_usage.status == "failed"
    assert world.manager._npc_ability_usage.timings[0].actor_id == "GUARD"
    assert len(model.calls) == 1 and performance.actor_id.get() == ""


async def test_cancelled_model_request_restores_actual_snapshot(combat_world, monkeypatch):
    world = combat_world
    model = ScriptModel(asyncio.CancelledError())
    await configured(world, monkeypatch, model)
    before = deepcopy(world.state.entity_states)
    with pytest.raises(asyncio.CancelledError):
        await run(world, "/fight GUARD")
    state, avatar, recovery = await saved(world)
    assert state.entity_states == before and avatar.hp == 100
    assert recovery.status == "pending" and recovery.backup is None
    assert world.manager._npc_ability_usage.status == "failed"
    assert performance.actor_id.get() == "" and len(model.calls) == 1


@pytest.mark.parametrize("protocol", ["native", "json"])
async def test_exhausted_invalid_choices_recover_without_default_attack(
    combat_world, monkeypatch, protocol
):
    world = combat_world
    model = ScriptModel(*(turn(call("invented", {}, f"call_{index}")) for index in range(3)))
    await configured(world, monkeypatch, model, protocol)
    before = deepcopy(world.state.entity_states)
    events = await run(world, "/fight GUARD")
    assert any(chunk.startswith("event: error") for chunk in events)
    state, avatar, recovery = await saved(world)
    assert state.entity_states == before and avatar.hp == 100
    assert recovery.status == "pending" and len(model.calls) == 3
    assert world.manager._npc_ability_usage.calls == 3


async def test_disconnect_after_selected_effect_restores_cost_and_state(combat_world, monkeypatch):
    world = combat_world
    model = ScriptModel(turn(call()))
    await configured(world, monkeypatch, model)
    before = deepcopy(world.state.entity_states)
    stream = world.manager.process_turn("/fight GUARD")
    first = await anext(stream)
    assert first.startswith("event: system") and world.manager.avatar.hp == 99
    await stream.aclose()
    state, avatar, recovery = await saved(world)
    assert state.entity_states == before and avatar.hp == 100
    assert recovery.status == "pending" and recovery.backup is None
    assert len(model.calls) == 1


async def test_npc_without_authored_abilities_keeps_existing_ai_without_inference(
    combat_world, monkeypatch
):
    world = combat_world
    model = ScriptModel()
    await configured(world, monkeypatch, model, authored=False)
    events = await run(world, "/fight GUARD")
    assert final(events)["combat"]["turn"] == "player"
    assert not model.calls and world.manager._npc_ability_usage.calls == 0
    assert load(world.manager.state).usage.calls == 0


@pytest.mark.parametrize("command", ["rest", "/say rest", "/debug on"])
async def test_reused_manager_cannot_reuse_old_recovery_for_new_unprotected_input(
    combat_world, monkeypatch, command
):
    world = combat_world
    model = ScriptModel(turn(call()))
    await configured(world, monkeypatch, model)
    await run(world, "/fight GUARD")
    assert world.manager.npc_ability_selector is not None
    bind(world.manager, command)
    assert world.manager.npc_ability_selector is None
    assert world.manager._npc_ability_usage is None and not world.manager.npc_ability_actor_ids
    assert len(model.calls) == 1


async def test_disabling_settings_clears_old_selector_on_reused_manager(combat_world, monkeypatch):
    world = combat_world
    model = ScriptModel(turn(call()))
    await configured(world, monkeypatch, model)
    await run(world, "/fight GUARD")
    current = load(world.manager.state)
    current.settings = current.settings.model_copy(update={"mode": "off", "action_tools": False})
    world.manager.state.entity_states = {
        **world.manager.state.entity_states,
        KEY: current.model_dump(mode="json"),
    }
    bind(world.manager, "/rest")
    assert world.manager.npc_ability_selector is None and world.manager._npc_ability_usage is None
