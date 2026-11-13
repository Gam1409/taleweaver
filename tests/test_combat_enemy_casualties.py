"""Enemy special effects and scripts share the normal casualty/outcome contract."""

import json
from unittest.mock import patch

import pytest
from sqlalchemy import func, select

from backend.models.chat import ChatMessage
from backend.models.world_entity import WorldEntity
from tests.combat_boundary_support import combat_world, deterministic_randint, enemy_combat, special

__all__ = ["combat_world"]
pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize("script", [False, True])
@pytest.mark.parametrize("enemy_first", [False, True])
async def test_last_enemy_special_finishes_casualty_and_loot_once(
    combat_world, script, enemy_first
):
    world = combat_world
    combat = await enemy_combat(world, hp=5, action=special(script=script), enemy_first=enemy_first)
    events = await _enemy_turn(world, combat)
    await world.db.commit()
    assert world.avatar.hp == 99
    assert combat["enemies"][0]["hp"] == 0 and combat["enemies"][0]["defeated"] is True
    assert combat["active"] is False and combat["outcome"] == "victory"
    assert combat["loot_pending"] is True and combat["turn"] == "player"
    assert world.avatar.exp == combat["xp_gained"] == 17
    assert [item["id"] for item in combat["loot_items"]] == ["TOKEN"]
    assert any("Guard defeat hook." in chunk for chunk in events)
    assert world.state.entity_states["GUARD"]["is_defeated"] is True
    assert world.state.entity_states["GUARD"]["is_attackable"] is False
    assert world.state.entity_states["__script_vars__"]["out_hook_runs"] == 1
    await _enemy_turn(world, combat)
    await world.db.commit()
    assert world.avatar.exp == 17
    assert [item["id"] for item in combat["loot_items"]] == ["TOKEN"]
    assert (
        await world.db.scalar(
            select(func.count())
            .select_from(ChatMessage)
            .where(ChatMessage.content == "Guard defeat hook.")
        )
        == 1
    )


async def test_self_casualty_does_not_end_fight_with_another_engaged_enemy(combat_world):
    world = combat_world
    combat = await enemy_combat(world, hp=5, action=special())
    other = await _other_enemy(world, combat)
    combat["initiative"] = [{"id": "GUARD"}, {"id": "PLAYER"}, {"id": "OTHER"}]
    await _enemy_turn(world, combat)
    assert combat["enemies"][0]["defeated"] is True
    assert other["hp"] == 12 and other["defeated"] is False
    assert combat["active"] is True and combat.get("outcome") is None
    assert world.avatar.exp == 17 and combat.get("loot_pending") is not True


async def test_enemy_special_script_resolves_every_casualty(combat_world):
    world = combat_world
    action = special(script=True)
    action["on_success_script"] += "\ntw.npcs.get('OTHER').modify_hp(-20)"
    combat = await enemy_combat(world, hp=5, action=action)
    await _other_enemy(world, combat)
    await _enemy_turn(world, combat)
    assert all(enemy["defeated"] for enemy in combat["enemies"])
    assert world.avatar.exp == 26
    assert combat["active"] is False and combat["outcome"] == "victory"


async def test_failed_enemy_special_script_still_resolves_casualty(combat_world):
    world = combat_world
    action = special(script=True)
    action["difficulty"] = 1000
    action["on_failure_script"] = action.pop("on_success_script")
    combat = await enemy_combat(world, hp=5, action=action)
    await _enemy_turn(world, combat)
    assert world.avatar.hp == 100
    assert combat["enemies"][0]["defeated"] is True
    assert world.avatar.exp == 17
    assert combat["active"] is False and combat["outcome"] == "victory"


@pytest.mark.parametrize("script", [False, True])
async def test_simultaneous_special_defeat_keeps_player_defeat_precedence(combat_world, script):
    world = combat_world
    combat = await enemy_combat(world, hp=5, action=special(script=script, player_lethal=True))
    await _enemy_turn(world, combat)
    await world.db.commit()
    assert world.avatar.hp == 0 and combat["enemies"][0]["hp"] == 0
    assert combat["active"] is False and combat["outcome"] == "defeat"
    assert world.avatar.exp == 0 and combat.get("loot_pending") is not True
    assert world.game.status == "game_over"


async def test_defeat_hook_player_damage_prevents_victory(combat_world):
    world = combat_world
    world.npc.metadata_json = {
        **world.npc.metadata_json,
        "on_defeat_script": "tw.player.damage(1000)",
    }
    combat = await enemy_combat(world, hp=5, action=special())
    await _enemy_turn(world, combat)
    assert world.avatar.hp == 0
    assert combat["outcome"] == "defeat" and combat["active"] is False
    assert combat.get("loot_pending") is not True


async def test_rest_turn_stream_and_persisted_save_enter_loot_after_enemy_recoil(combat_world):
    world = combat_world
    world.npc.hp = 5
    world.npc.metadata_json = {
        **world.npc.metadata_json,
        "special_actions": [special()],
        "special_chance": 100,
    }
    await world.db.commit()
    with (
        patch(
            "backend.engine.combat.special_attacks.random.randint",
            side_effect=deterministic_randint,
        ),
        patch("backend.engine.gameplay.combat.enemy_ai.random.random", return_value=0.0),
    ):
        _ = [chunk async for chunk in world.manager.process_turn("/fight GUARD")]
        events = [chunk async for chunk in world.manager.process_turn("/rest")]
    final = next(chunk for chunk in events if chunk.startswith("event: final\n"))
    payload = json.loads(final.split("data: ", 1)[1])
    assert payload["combat"]["active"] is False
    assert payload["combat"]["outcome"] == "victory"
    assert payload["combat"]["loot_pending"] is True
    await world.db.refresh(world.state)
    await world.db.refresh(world.avatar)
    assert world.state.entity_states["__combat__"]["outcome"] == "victory"
    assert world.state.entity_states["GUARD"]["is_defeated"] is True
    assert world.avatar.exp == 17


async def _enemy_turn(world, combat):
    with (
        patch(
            "backend.engine.combat.special_attacks.random.randint",
            side_effect=deterministic_randint,
        ),
        patch("backend.engine.gameplay.combat.enemy_ai.random.random", return_value=0.0),
    ):
        return [
            chunk
            async for chunk in world.manager.combat._advance_until_player(
                combat, skip_current=False
            )
        ]


async def _other_enemy(world, combat):
    other = WorldEntity(
        id="OTHER",
        session_id=world.game.id,
        entity_type="NPC",
        name="Other guard",
        description="Another synthetic guard.",
        current_scene_id="ARENA",
        hp=12,
        max_hp=12,
        metadata_json={"exp_reward": 9},
        inventory=[],
    )
    world.db.add(other)
    await world.db.flush()
    entry = await world.manager.combat._build_enemy_entry(other, engaged=True)
    combat["enemies"].append(entry)
    return entry
