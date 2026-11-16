"""Weapon damage cannot heal a target, including negative signed dice totals."""

from unittest.mock import patch

import pytest

from backend.engine.gameplay.combat.attacks import apply_strength_bonus
from backend.engine.skill_check import roll_attack, roll_dice_detailed
from tests.combat_boundary_support import combat_world, weapon_combat

__all__ = ["combat_world"]
pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize("hit_roll", [10, 20])
async def test_weapon_roll_cannot_be_negative(combat_world, hit_roll):
    with patch("backend.engine.skill_check.random.randint", side_effect=[hit_roll, 1]):
        result = roll_attack(combat_world.avatar, "dexterity", 10, "1d4-4")
    assert result["is_hit"]
    assert result["is_crit"] == (hit_roll == 20)
    assert result["damage_total"] == 0
    assert result["damage_bonus"] == -4 and result["damage_rolls"] == [1]


async def test_generic_signed_dice_keeps_its_signed_total():
    with patch("backend.engine.skill_check.random.randint", return_value=1):
        result = roll_dice_detailed("1d4-4")
    assert result["total"] == -3


@pytest.mark.parametrize("actor", ["player", "enemy"])
@pytest.mark.parametrize("hit_roll", [10, 20])
async def test_weapon_hit_cannot_heal_full_health_target(combat_world, actor, hit_roll):
    world = combat_world
    combat = await weapon_combat(world)
    with patch("backend.engine.skill_check.random.randint", side_effect=[hit_roll, 1]):
        data, hp_after = await _attack(world, combat, actor)
    assert hp_after == 100
    assert data["success"] is True
    assert data["crit"] == (hit_roll == 20)
    assert data["effects"][0]["delta"] == 0


@pytest.mark.parametrize("actor", ["player", "enemy"])
@pytest.mark.parametrize("hit_roll", [10, 20])
@pytest.mark.parametrize("strength", [-5, 0, 2, 5, 8])
@pytest.mark.parametrize("dice,raw_total", [("1d4-4", -3), ("1d4+2", 3)])
async def test_weapon_strength_uses_signed_roll_before_final_floor(
    combat_world, actor, hit_roll, strength, dice, raw_total
):
    world = combat_world
    combat = await weapon_combat(world, dice)
    combatant = combat["player"] if actor == "player" else combat["enemies"][0]
    combatant["modifiers"]["strength"] = strength
    expected = max(0, raw_total * (2 if hit_roll == 20 else 1) + strength)
    with patch("backend.engine.skill_check.random.randint", side_effect=[hit_roll, 1]):
        data, hp_after = await _attack(world, combat, actor)
    assert hp_after == 100 - expected
    assert data["effects"][0]["delta"] == -expected


@pytest.mark.parametrize("actor", ["player", "enemy"])
@pytest.mark.parametrize("strength", [-5, 0, 5])
async def test_weapon_handler_defends_against_negative_producer_output(
    combat_world, actor, strength, monkeypatch
):
    world = combat_world
    combat = await weapon_combat(world)
    combatant = combat["player"] if actor == "player" else combat["enemies"][0]
    combatant["modifiers"]["strength"] = strength
    with patch("backend.engine.skill_check.random.randint", side_effect=[10, 1]):
        roll = roll_attack(world.avatar, "dexterity", 10, "1d4-4")
    roll["damage_total"] = -3
    monkeypatch.setattr(
        "backend.api.routes.adventures.gameplay_logic.roll_attack", lambda *_args: dict(roll)
    )
    data, hp_after = await _attack(world, combat, actor)
    expected = max(0, -3 + strength)
    assert hp_after == 100 - expected
    assert data["effects"][0]["delta"] == -expected


@pytest.mark.parametrize(
    "base_damage,strength,expected", [(-3, 0, 0), (-3, 1, 0), (2, -1, 1), (2, -3, 0), (2, 4, 6)]
)
async def test_strength_adjustment_keeps_shared_damage_boundary_nonnegative(
    base_damage, strength, expected
):
    original = {"is_hit": True, "damage_total": base_damage, "damage_bonus": -4}
    adjusted = apply_strength_bonus(original, strength)
    assert adjusted["damage_total"] == expected
    assert original["damage_total"] == base_damage


async def _attack(world, combat, actor):
    if actor == "player":
        result = await world.manager.combat._player_attack(combat, "")
        return result["data"], combat["enemies"][0]["hp"]
    _, data = await world.manager.combat._enemy_weapon_attack(
        combat, combat["enemies"][0], world.npc
    )
    return data, world.avatar.hp
