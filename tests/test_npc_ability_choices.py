"""Host-selected RPG abilities retain initiative, resources and existing consequences."""

from copy import deepcopy
from unittest.mock import AsyncMock

import pytest

from backend.engine.gameplay.combat.ability_choices import Choice, prepare, resolve
from tests.combat_boundary_support import combat_world, deterministic_randint, enemy_combat

__all__ = ["combat_world"]


def ability(**changes):
    return {
        "id": "SPARK",
        "name": "Spark",
        "description": "A short flash.",
        "category": "MAGIC",
        "cost_type": "mana",
        "cost": 7,
        "difficulty": 1,
        "effects": [{"target": "target", "stat": "hp", "amount": "-1"}],
        **changes,
    }


async def test_catalog_exposes_only_the_bound_npcs_abilities(combat_world):
    world = combat_world
    action = ability(on_success_script="PRIVATE_SCRIPT", on_success_text="PRIVATE_TEXT")
    combat = await enemy_combat(world, action=action)
    turn = await prepare(world.manager.combat, combat, "GUARD")
    assert [row["id"] for row in turn.context["abilities"]] == ["SPARK"]
    assert turn.context["actor_id"] == "GUARD"
    assert "PRIVATE_SCRIPT" not in str(turn.context)
    assert "PRIVATE_TEXT" not in str(turn.context)
    assert "inventory" not in turn.context


async def test_selecting_a_definition_does_not_apply_its_effects(combat_world):
    world = combat_world
    combat = await enemy_combat(world, action=ability())
    turn = await prepare(world.manager.combat, combat, "GUARD")
    before = deepcopy(combat)
    action = await resolve(world.manager.combat, combat, Choice(turn.frame, "SPARK", "PLAYER"))
    assert action["id"] == "SPARK" and combat == before
    assert world.avatar.hp == 100


@pytest.mark.parametrize(
    "identifier,target", [("invented", "PLAYER"), ("SPARK", "OTHER"), ("SPARK", "GUARD")]
)
async def test_unknown_ability_or_target_cannot_mutate_resources(combat_world, identifier, target):
    world = combat_world
    combat = await enemy_combat(world, action=ability())
    turn = await prepare(world.manager.combat, combat, "GUARD")
    before = deepcopy(combat)
    with pytest.raises(ValueError):
        await resolve(world.manager.combat, combat, Choice(turn.frame, identifier, target))
    assert combat == before and world.avatar.hp == 100


@pytest.mark.parametrize("change", ["resource", "turn", "encounter", "scene"])
async def test_a_stale_frame_cannot_authorize_a_later_ability(combat_world, change):
    world = combat_world
    combat = await enemy_combat(world, action=ability())
    turn = await prepare(world.manager.combat, combat, "GUARD")
    if change == "resource":
        combat["enemies"][0]["mana"] -= 1
    if change == "turn":
        combat["turn_index"] = 1
    if change == "encounter":
        combat["encounter_id"] = "another-encounter"
    if change == "scene":
        world.state.current_scene_id = "ELSEWHERE"
    before = deepcopy(combat)
    with pytest.raises(ValueError):
        await resolve(world.manager.combat, combat, Choice(turn.frame, "SPARK", "PLAYER"))
    assert combat == before and world.avatar.hp == 100


async def test_ability_cost_is_checked_again_before_resolution(combat_world):
    world = combat_world
    combat = await enemy_combat(world, action=ability())
    combat["enemies"][0]["mana"] = 1
    turn = await prepare(world.manager.combat, combat, "GUARD")
    assert turn.context["abilities"][0]["available"] is False
    with pytest.raises(ValueError, match="resource"):
        await resolve(world.manager.combat, combat, Choice(turn.frame, "SPARK", "PLAYER"))
    assert combat["enemies"][0]["mana"] == 1


async def test_adventure_damage_policy_is_preserved(combat_world):
    world = combat_world
    world.manager.adventure.npcs_can_damage_protagonist = False
    combat = await enemy_combat(world, action=ability())
    turn = await prepare(world.manager.combat, combat, "GUARD")
    assert turn.context["abilities"][0]["available"] is False
    with pytest.raises(ValueError, match="disables"):
        await resolve(world.manager.combat, combat, Choice(turn.frame, "SPARK", "PLAYER"))
    assert world.avatar.hp == 100


async def test_selected_ability_spends_one_existing_initiative_turn(combat_world, monkeypatch):
    world = combat_world
    combat = await enemy_combat(world, action=ability())
    selected = []

    async def choose(turn):
        selected.append(turn)
        return Choice(turn.frame, "SPARK", "PLAYER")

    world.manager.npc_ability_selector = choose
    monkeypatch.setattr(
        "backend.engine.combat.special_attacks.random.randint", deterministic_randint
    )
    monkeypatch.setattr(
        world.manager.combat,
        "_choose_enemy_special",
        lambda *_: pytest.fail("Selected action must not use random AI."),
    )
    events = [chunk async for chunk in world.manager.combat._advance_until_player(combat, False)]
    assert events and len(selected) == 1
    assert world.avatar.hp == 99
    assert combat["enemies"][0]["mana"] == 93
    assert combat["turn"] == "player" and combat["turn_index"] == 1
    again = [chunk async for chunk in world.manager.combat._advance_until_player(combat, False)]
    assert not again and len(selected) == 1
    assert world.avatar.hp == 99 and combat["enemies"][0]["mana"] == 93
    with pytest.raises(ValueError, match="turn"):
        await resolve(world.manager.combat, combat, Choice(selected[0].frame, "SPARK", "PLAYER"))


async def test_failed_selected_ability_keeps_its_cost_and_failure_hook(combat_world, monkeypatch):
    world = combat_world
    combat = await enemy_combat(
        world, action=ability(difficulty=1000, on_failure_text="The flash fades.")
    )

    async def choose(turn):
        return Choice(turn.frame, "SPARK", "PLAYER")

    world.manager.npc_ability_selector = choose
    monkeypatch.setattr(
        "backend.engine.combat.special_attacks.random.randint", deterministic_randint
    )
    events = [chunk async for chunk in world.manager.combat._advance_until_player(combat, False)]
    assert any("The flash fades." in chunk for chunk in events)
    assert world.avatar.hp == 100 and combat["enemies"][0]["mana"] == 93
    entry = next(row for row in combat["log"] if row["type"] == "enemy_action")
    assert entry["data"]["success"] is False


async def test_invalid_selection_does_not_fall_back_to_an_unrequested_attack(combat_world):
    world = combat_world
    combat = await enemy_combat(world, action=ability())

    async def choose(turn):
        return Choice(turn.frame, "invented", "PLAYER")

    world.manager.npc_ability_selector = choose
    with pytest.raises(ValueError):
        _ = [chunk async for chunk in world.manager.combat._advance_until_player(combat, False)]
    assert combat["turn_index"] == 0
    assert world.avatar.hp == 100 and combat["enemies"][0]["mana"] == 100


async def test_vn_mode_cannot_obtain_a_combat_frame(combat_world):
    world = combat_world
    combat = await enemy_combat(world, action=ability())
    world.manager.adventure.rule_enforcement_mode = "vn"
    with pytest.raises(ValueError):
        await prepare(world.manager.combat, combat, "GUARD")


async def test_self_ability_uses_the_npcs_own_resources_and_target(combat_world, monkeypatch):
    world = combat_world
    heal = ability(action_type="HEAL", effects=[{"target": "self", "stat": "hp", "amount": "+5"}])
    combat = await enemy_combat(world, hp=80, action=heal)

    async def choose(turn):
        assert turn.context["abilities"][0]["target_ids"] == ["GUARD"]
        return Choice(turn.frame, "SPARK", "GUARD")

    world.manager.npc_ability_selector = choose
    monkeypatch.setattr(
        "backend.engine.combat.special_attacks.random.randint", deterministic_randint
    )
    _ = [chunk async for chunk in world.manager.combat._advance_until_player(combat, False)]
    assert combat["enemies"][0]["hp"] == 85
    assert combat["enemies"][0]["mana"] == 93 and world.avatar.hp == 100


async def test_a_declined_selection_rechecks_state_before_automatic_fallback(combat_world):
    world = combat_world
    combat = await enemy_combat(world, action=ability())

    async def choose(_turn):
        combat["turn_index"] = 1

    world.manager.npc_ability_selector = choose
    with pytest.raises(ValueError, match="turn"):
        _ = [chunk async for chunk in world.manager.combat._advance_until_player(combat, False)]
    assert world.avatar.hp == 100 and combat["enemies"][0]["mana"] == 100


async def test_unselected_actors_keep_the_original_combat_driver(combat_world):
    world = combat_world
    combat = await enemy_combat(world, action=ability())
    callback = AsyncMock(
        side_effect=AssertionError("Unselected actor must not call the tool selector.")
    )
    world.manager.npc_ability_selector = callback
    world.manager.npc_ability_actor_ids = {"OTHER"}
    _ = [chunk async for chunk in world.manager.combat._advance_until_player(combat, False)]
    callback.assert_not_awaited()


async def test_npc_without_a_resource_pool_retains_legacy_ability_affordability(combat_world):
    world = combat_world
    combat = await enemy_combat(world, action=ability())
    enemy = combat["enemies"][0]
    enemy["mana"] = enemy["max_mana"] = 0
    turn = await prepare(world.manager.combat, combat, "GUARD")
    assert turn.context["abilities"][0]["available"] is True
    assert turn.context["abilities"][0]["cost"]["free_without_pool"] is True
    assert (await resolve(world.manager.combat, combat, Choice(turn.frame, "SPARK")))[
        "id"
    ] == "SPARK"


async def test_an_edited_authored_ability_invalidates_the_old_choice(combat_world):
    world = combat_world
    combat = await enemy_combat(world, action=ability())
    turn = await prepare(world.manager.combat, combat, "GUARD")
    world.npc.metadata_json = {**world.npc.metadata_json, "special_actions": [ability(cost=50)]}
    with pytest.raises(ValueError, match="changed"):
        await resolve(world.manager.combat, combat, Choice(turn.frame, "SPARK", "PLAYER"))
    assert world.avatar.hp == 100 and combat["enemies"][0]["mana"] == 100


async def test_selected_ability_runs_the_original_success_script(combat_world, monkeypatch):
    world = combat_world
    combat = await enemy_combat(
        world,
        action=ability(
            on_success_script="tw.vars.set('selected_spell_runs', tw.vars.get('selected_spell_runs', 0) + 1)"
        ),
    )

    async def choose(turn):
        return Choice(turn.frame, "SPARK", "PLAYER")

    world.manager.npc_ability_selector = choose
    monkeypatch.setattr(
        "backend.engine.combat.special_attacks.random.randint", deterministic_randint
    )
    _ = [chunk async for chunk in world.manager.combat._advance_until_player(combat, False)]
    assert world.state.entity_states["__script_vars__"]["selected_spell_runs"] == 1
    assert combat["enemies"][0]["mana"] == 93
