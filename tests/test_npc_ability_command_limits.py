"""Combat admission covers actual initiative participants and every owner turn."""

from copy import deepcopy

import pytest
from pydantic import ValidationError

from backend.engine.chpm import capacity
from backend.engine.chpm.schema import KernelState, Settings
from backend.engine.chpm.state import KEY, load
from backend.engine.chpm.template_settings import Defaults
from backend.models.world_entity import WorldEntity
from tests.combat_boundary_support import combat_world, enemy_combat
from tests.test_npc_ability_choices import ability
from tests.test_npc_ability_port import ScriptModel, call, turn
from tests.test_npc_ability_process_turn import configured, final, run, saved

__all__ = ["combat_world"]


def configure_budget(world, *, rounds=1, actors=None, active=1):
    settings = Settings(
        control_scope="combat_actions",
        mode="live",
        workflow="integrated",
        action_tools=True,
        actor_ids=actors or ["GUARD"],
        agent_steps=rounds,
        max_active_npcs=active,
        max_calls_per_turn=3 * active * rounds,
        tool_protocol="native",
    )
    world.state.entity_states = {
        **world.state.entity_states,
        KEY: KernelState(settings=settings).model_dump(mode="json"),
    }
    return settings


def npcs_first(participants):
    ordered = sorted(participants, key=lambda row: (row["id"] == "PLAYER", row["id"]))
    return [{**row, "total": 20 - index} for index, row in enumerate(ordered)]


@pytest.mark.parametrize("other", ["off_scene", "no_abilities"])
async def test_ineligible_roster_entries_do_not_consume_active_combat_slots(
    combat_world, monkeypatch, other
):
    world = combat_world
    model = ScriptModel(turn(call()))
    await configured(world, monkeypatch, model)
    monkeypatch.setattr("backend.engine.gameplay.combat.rounds.roll_initiative", npcs_first)
    monkeypatch.setattr("backend.engine.gameplay.combat.narration.random.random", lambda: 1.0)
    world.db.add(
        WorldEntity(
            id="ABSENT",
            session_id=world.game.id,
            entity_type="NPC",
            name="Other guard",
            description="A previously encountered guard.",
            current_scene_id="ELSEWHERE" if other == "off_scene" else "ARENA",
            hp=100,
            metadata_json={"attack_mode": "ATTACK_ON_SIGHT"},
        )
    )
    configure_budget(world, actors=["ABSENT", "GUARD"])
    await world.db.commit()

    events = await run(world, "/fight GUARD")

    assert not any(chunk.startswith("event: error") for chunk in events)
    assert len(model.calls) == 1
    combat = final(events)["combat"]
    selected = next(row for row in combat["log"] if row.get("data", {}).get("kind") == "special")
    assert selected["data"]["actor"] == "GUARD"
    assert load(world.manager.state).usage.calls == 1


async def test_combat_quota_admits_actual_initiative_order_and_counts_distinct_actors(
    combat_world, monkeypatch
):
    world = combat_world
    model = ScriptModel(turn(call()))
    await configured(world, monkeypatch, model)
    world.db.add(
        WorldEntity(
            id="AAA",
            session_id=world.game.id,
            entity_type="NPC",
            name="Other guard",
            description="An armed guard.",
            current_scene_id="ARENA",
            hp=100,
            mana=100,
            max_mana=100,
            metadata_json={
                "attack_mode": "ATTACK_ON_SIGHT",
                "special_actions": [ability()],
                "special_chance": 0,
            },
        )
    )

    def guard_then_others(participants):
        ordered = sorted(
            participants, key=lambda row: (row["id"] != "GUARD", row["id"] == "PLAYER")
        )
        return [{**row, "total": 20 - index} for index, row in enumerate(ordered)]

    monkeypatch.setattr("backend.engine.gameplay.combat.rounds.roll_initiative", guard_then_others)
    monkeypatch.setattr("backend.engine.gameplay.combat.narration.random.random", lambda: 1.0)
    configure_budget(world, actors=["AAA", "GUARD"])
    await world.db.commit()

    events = await run(world, "/fight GUARD")

    assert not any(chunk.startswith("event: error") for chunk in events)
    assert len(model.calls) == 1
    combat = final(events)["combat"]
    actions = [row["data"] for row in combat["log"] if row["type"] == "enemy_action"]
    assert [(row["actor"], row["kind"]) for row in actions] == [
        ("GUARD", "special"),
        ("AAA", "attack"),
    ]


def repair_replies(count, rounds):
    for frame in range(count):
        for attempt in range(rounds):
            name = "use_ability" if attempt == rounds - 1 else "not_offered"
            yield turn(call(name, identifier=f"frame_{frame}_call_{attempt}"))


@pytest.mark.parametrize("restored,actions", [(False, 2), (True, 3)])
@pytest.mark.parametrize("rounds", [1, 3])
@pytest.mark.parametrize("actor_count", [1, 2])
async def test_normal_and_restored_commands_fund_each_existing_initiative_turn(
    combat_world, monkeypatch, restored, actions, rounds, actor_count
):
    world = combat_world
    total_actions = actions * actor_count
    model = ScriptModel(*repair_replies(total_actions, rounds))
    await configured(world, monkeypatch, model)
    scripted = ability(
        on_success_script=(
            "tw.vars.set('selected_runs', tw.vars.get('selected_runs', 0) + 1)\n"
            "tw.npcs.get('GUARD').attack()"
        )
    )
    combat = await enemy_combat(world, action=scripted, enemy_first=False)
    actors = ["GUARD"]
    if actor_count == 2:
        other = WorldEntity(
            id="OTHER",
            session_id=world.game.id,
            entity_type="NPC",
            name="Other guard",
            description="A second participant in the same initiative.",
            current_scene_id="ARENA",
            hp=100,
            max_hp=100,
            mana=100,
            max_mana=100,
            metadata_json={"special_actions": [scripted]},
        )
        world.db.add(other)
        await world.db.flush()
        combat["enemies"].append(await world.manager.combat._build_enemy_entry(other, True))
        combat["initiative"].append({"id": "OTHER"})
        actors.append("OTHER")
    if not restored:
        combat.update(turn="player", turn_index=0)
    world.manager.combat._set_combat_state(combat)
    settings = configure_budget(world, rounds=rounds, actors=actors, active=actor_count)
    monkeypatch.setattr("backend.engine.gameplay.combat.rounds.roll_initiative", npcs_first)
    await world.db.commit()

    events = await run(world, "/rest")

    assert not any(chunk.startswith("event: error") for chunk in events)
    combat = final(events)["combat"]
    assert len(model.calls) == total_actions * rounds
    assert capacity.required_calls(settings) == 3 * actor_count * rounds
    assert combat["turn"] == "player" and combat["turn_index"] == actor_count
    assert combat["round"] == (3 if restored else 2)
    assert len([row for row in combat["log"] if row["type"] == "enemy_action"]) == total_actions
    state, avatar, recovery = await saved(world)
    assert avatar.hp == 100 - total_actions
    assert all(state.entity_states[actor]["mana"] == 100 - 7 * actions for actor in actors)
    assert state.entity_states["__script_vars__"]["selected_runs"] == total_actions
    assert load(state).usage.calls == total_actions * rounds
    assert recovery.status == "command_complete"


def test_combat_budget_reserves_all_three_owner_turns_without_raising_the_call_cap():
    values = {
        "control_scope": "combat_actions",
        "mode": "live",
        "workflow": "integrated",
        "action_tools": True,
        "actor_ids": ["GUARD"],
        "agent_steps": 3,
        "max_calls_per_turn": 9,
    }
    valid = Settings(**values)
    assert capacity.required_calls(valid) == 9
    legacy = KernelState(settings=Settings(**{**values, "max_calls_per_turn": 8}))
    assert KernelState.model_validate_json(legacy.model_dump_json()) == legacy
    assert capacity.required_calls(legacy.settings) == 9
    with pytest.raises(ValidationError, match="budget"):
        Defaults(**{**values, "max_calls_per_turn": 8})
    with pytest.raises(ValidationError, match="budget"):
        Defaults(**{**values, "actor_ids": ["A", "B", "C"], "max_calls_per_turn": 25})
    assert Settings.model_json_schema()["properties"]["max_calls_per_turn"]["maximum"] == 25


@pytest.mark.parametrize("budget", [3, 8])
@pytest.mark.parametrize("command", ["/fight GUARD", "/attack GUARD"])
async def test_underfunded_legacy_combat_pauses_before_requests_and_preserves_saved_state(
    combat_world, monkeypatch, budget, command
):
    world = combat_world
    model = ScriptModel(turn(call()))
    await configured(world, monkeypatch, model)
    if command == "/attack GUARD":
        combat = await enemy_combat(world, action=ability(), enemy_first=False)
        combat.update(turn="player", turn_index=0)
        world.manager.combat._set_combat_state(combat)
    value = deepcopy(world.state.entity_states)
    value[KEY]["settings"]["max_calls_per_turn"] = budget
    world.state.entity_states = deepcopy(value)
    await world.db.commit()

    events = await run(world, command)

    errors = [chunk for chunk in events if chunk.startswith("event: error")]
    assert len(errors) == 1 and "at least 9" in errors[0]
    assert not any(chunk.startswith("event: final") for chunk in events)
    assert not model.calls
    state, avatar, recovery = await saved(world)
    assert state.entity_states == value and avatar.hp == avatar.stamina == 100
    assert load(state).settings.max_calls_per_turn == budget
    assert recovery.status == "pending" and recovery.backup is None
