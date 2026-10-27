"""The public turn-manager facade must preserve its delegates' async contracts."""

import inspect
from typing import get_type_hints

import pytest
import pytest_asyncio

from backend.api.routes.adventures.gameplay_logic import GameTurnManager
from backend.models.world_entity import WorldEntity
from tests.conftest import TestSessionLocal
from tests.test_game_loop import _seed_game_context


@pytest_asyncio.fixture
async def manager():
    async with TestSessionLocal() as db:
        user, adventure, avatar, state = await _seed_game_context(db)
        turn = GameTurnManager(db, state.session_id, user)
        turn.adventure, turn.avatar, turn.state = adventure, avatar, state
        yield turn


async def test_switch_facade_returns_awaited_text(manager):
    response = await manager._execute_switch_command("")
    assert response.startswith("Usage: /switch")


async def test_container_facade_resolves_three_fields_and_normalizes_raw_items(manager):
    item = WorldEntity(
        id="POTION",
        session_id=manager.game_id,
        entity_type="OBJECT",
        name="Potion",
        description="A healing potion.",
        current_scene_id="START",
        item_type="CONSUMABLE",
        metadata_json={"hp_change": 5},
    )
    chest = WorldEntity(
        id="CHEST",
        session_id=manager.game_id,
        entity_type="OBJECT",
        name="Chest",
        description="A wooden chest.",
        current_scene_id="START",
        item_type="CONTAINER",
        inventory=["POTION", {"id": "NOTE", "name": "Note"}],
    )
    manager.db.add_all([item, chest])
    await manager.db.flush()
    scene_container, carried_container, index = await manager._resolve_container_target("CHEST")
    assert scene_container is chest and carried_container is None and index is None
    raw = await manager._get_container_inventory(chest, None)
    assert raw[0] == "POTION"
    normalized = await manager._normalize_container_items(raw)
    assert [entry["id"] for entry in normalized] == ["POTION", "NOTE"]
    assert normalized[0]["hp_change"] == 5
    assert await manager._normalize_container_item_ref(None) is None
    assert await manager._move_container_item_to_inventory(normalized[0]) is None
    assert item.is_in_inventory and item.current_scene_id == "INVENTORY"
    assert await manager._move_container_item_to_scene(normalized[0]) is True
    assert not item.is_in_inventory and item.current_scene_id == "START"
    assert await manager._move_container_item_to_scene({"id": "MISSING"}) is False
    assert await manager._clear_container_inventory(chest, None, None) is None
    assert await manager._get_container_inventory(chest, None) == []


async def test_container_facade_preserves_carried_container_position(manager):
    manager.avatar.inventory = [{"id": "BAG", "item_type": "CONTAINER", "inventory": ["NOTE"]}]
    scene, carried, index = await manager._resolve_container_target("BAG")
    assert scene is None and carried["id"] == "BAG" and index == 0
    assert await manager._get_container_inventory(scene, carried) == ["NOTE"]
    await manager._clear_container_inventory(scene, carried, index)
    assert manager.avatar.inventory[0]["inventory"] == []


async def test_enemy_turn_facade_is_an_async_stream(manager):
    assert [event async for event in manager._resolve_enemy_turn(combat={"active": False})] == []


@pytest.mark.parametrize("component", ["interactions", "combat", "guardrails"])
async def test_explicit_facade_contracts_match_delegates(manager, component):
    delegate = getattr(manager, component)
    checked = 0
    for name, wrapper in vars(GameTurnManager).items():
        if not callable(wrapper) or not hasattr(delegate, name):
            continue
        signature = inspect.signature(wrapper)
        if any(p.kind == p.VAR_POSITIONAL for p in signature.parameters.values()):
            continue
        if f"self.{component}.{name}(" not in inspect.getsource(wrapper):
            continue
        target = getattr(type(delegate), name)
        assert get_type_hints(wrapper).get("return") == get_type_hints(target).get("return"), name
        assert inspect.iscoroutinefunction(wrapper) == inspect.iscoroutinefunction(target), name
        assert inspect.isasyncgenfunction(wrapper) == inspect.isasyncgenfunction(target), name
        checked += 1
    assert checked > 0
