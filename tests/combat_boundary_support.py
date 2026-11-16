"""Synthetic combat records with real storage and deterministic combat inputs."""

from types import SimpleNamespace

import pytest_asyncio
from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.api.routes.adventures.gameplay_logic import GameTurnManager
from backend.engine.combat.special_attacks import normalize_special_action
from backend.engine.manifest_apply.objects import item_numbers, object_metadata
from backend.engine.world_schemas import SpecialActionSchema, WorldObjectSchema
from backend.models import Base
from backend.models.adventure_template import AdventureTemplate
from backend.models.avatar import Avatar
from backend.models.game_session import GameSession
from backend.models.session_state import SessionState
from backend.models.user import User
from backend.models.world_entity import WorldEntity, WorldScene


def _foreign_keys(connection, _record):
    connection.execute("PRAGMA foreign_keys=ON")


@pytest_asyncio.fixture
async def combat_world():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    event.listen(engine.sync_engine, "connect", _foreign_keys)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as db:
        world = await _seed_combat(db)
        yield world
    await engine.dispose()


async def _seed_combat(db):
    user = User(id="combat-owner", username="combat-owner", hashed_password="synthetic")
    db.add(user)
    await db.flush()
    adventure = AdventureTemplate(
        id="combat-template", owner_id=user.id, title="Combat boundary", rule_enforcement_mode="rpg"
    )
    db.add(adventure)
    await db.flush()
    avatar = Avatar(
        id="combat-avatar", user_id=user.id, template_id=adventure.id,
        name="Keeper", hp=100, max_hp=100, mana=100, max_mana=100,
        stamina=100, max_stamina=100, strength=10, dexterity=10,
        intelligence=10, wisdom=10, charisma=10, armor_class=10,
        stats={}, inventory=[], equipment={}, status_effects=[], exp=0,
    )  # fmt: skip
    db.add(avatar)
    await db.flush()
    game = GameSession(
        id="combat-session", user_id=user.id, avatar_id=avatar.id, template_id=adventure.id
    )
    db.add(game)
    await db.flush()
    state = SessionState(
        session_id=game.id,
        user_id=user.id,
        avatar_id=avatar.id,
        template_id=adventure.id,
        current_scene_id="ARENA",
        entity_states={},
    )
    npc = WorldEntity(
        id="GUARD",
        session_id=game.id,
        entity_type="NPC",
        name="Guard",
        description="A synthetic guard.",
        current_scene_id="ARENA",
        hp=100,
        max_hp=100,
        stamina=100,
        max_stamina=100,
        mana=100,
        max_mana=100,
        inventory=[{"id": "TOKEN", "name": "Token", "item_type": "PICKABLE"}],
        metadata_json={
            "exp_reward": 17,
            "on_defeat_text": "Guard defeat hook.",
            "on_defeat_script": "tw.vars.set('out_hook_runs', tw.vars.get('out_hook_runs', 0) + 1)",
        },
    )
    db.add_all(
        [
            state,
            npc,
            WorldScene(id="ARENA", session_id=game.id, label="Arena", description="A room."),
        ]
    )
    await db.commit()
    manager = GameTurnManager(db, game.id, user)
    manager.avatar, manager.state, manager.adventure = avatar, state, adventure
    return SimpleNamespace(db=db, manager=manager, avatar=avatar, npc=npc, state=state, game=game)


async def enemy_combat(world, *, hp=100, action=None, enemy_first=True):
    world.npc.hp = hp
    if action:
        world.npc.metadata_json = {
            **world.npc.metadata_json,
            "special_actions": [action],
            "special_chance": 100,
        }
    await world.db.commit()
    entry = await world.manager.combat._build_enemy_entry(world.npc, engaged=True)
    order = ["GUARD", "PLAYER"] if enemy_first else ["PLAYER", "GUARD"]
    combat = {
        "active": True,
        "round": 1,
        "turn": "enemy",
        "turn_index": 0 if enemy_first else 1,
        "initiative": [{"id": actor} for actor in order],
        "enemies": [entry],
        "target_id": "GUARD",
        "log": [],
    }
    world.manager.combat._sync_combat_player_snapshot(combat)
    return combat


async def weapon_combat(world, damage_dice="1d4-4"):
    definition = WorldObjectSchema(
        id="PRACTICE_STICK",
        name="Practice stick",
        description="A training weapon.",
        start_scene_id="ARENA",
        spatial_position="On a rack.",
        is_hidden=False,
        is_portable=True,
        item_type="WEAPON",
        damage_dice=damage_dice,
        weapon_cost_value=0,
    )
    raw = definition.model_dump()
    metadata = object_metadata(raw, item_numbers(raw, {}))
    assert metadata["damage_dice"] == damage_dice
    weapon = WorldEntity(
        id=definition.id,
        session_id=world.game.id,
        entity_type="OBJECT",
        name=definition.name,
        description=definition.description,
        current_scene_id="ARENA",
        item_type="WEAPON",
        metadata_json=metadata,
    )
    world.db.add(weapon)
    world.avatar.equipment = {
        "MainHand": {"id": weapon.id, "name": weapon.name, "metadata_json": metadata}
    }
    world.npc.metadata_json = {**world.npc.metadata_json, "equipped_weapon_id": weapon.id}
    return await enemy_combat(world)


def special(*, script=False, player_lethal=False):
    source = {
        "id": "RECOIL",
        "name": "Recoil burst",
        "description": "A synthetic recoil action.",
        "action_type": "ATTACK",
        "cost": 0,
        "difficulty": 1,
        "effects": [
            {"target": "target", "stat": "hp", "amount": "-100" if player_lethal else "-1"}
        ],
    }
    if script:
        source["on_success_script"] = "tw.npcs.get('GUARD').modify_hp(-10)"
    else:
        source["effects"].append({"target": "self", "stat": "hp", "amount": "-10"})
    SpecialActionSchema.model_validate(source)
    assert normalize_special_action(source) is not None
    return source


def deterministic_randint(_lower, upper):
    return 19 if upper == 20 else 1
