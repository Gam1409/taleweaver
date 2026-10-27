"""Characterize turn mutation ordering and preservation across domain extraction."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.api.routes.adventures.gameplay_logic import GameTurnManager
from backend.api.routes.adventures.turn_state_applier import TurnStateApplier
from backend.engine.rule_engine import GameEvent, InventoryItem, WorldEntityUpdate
from backend.models.world_entity import WorldEntity
from tests.conftest import TestSessionLocal
from tests.test_game_loop import _seed_game_context


@pytest.mark.parametrize("replacement", [False, True])
async def test_consumable_ids_are_reserved_across_inventory_and_scene_items(replacement):
    avatar = SimpleNamespace(
        inventory=[{"id": "POTION", "name": "Potion", "image_url": "/data/potion.png"}]
    )
    manager = SimpleNamespace(
        avatar=avatar,
        game_id="session",
        _collect_existing_item_ids=AsyncMock(return_value={"POTION", "POTION_COPY_1"}),
    )
    event = GameEvent(
        new_inventory_items=[InventoryItem(id="POTION", name="Potion", item_type="CONSUMABLE")],
        spawned_items=[InventoryItem(id="POTION", name="Potion", item_type="CONSUMABLE")],
        removed_inventory_item_ids=["POTION"] if replacement else None,
    )
    if replacement:
        event.new_inventory_items[0].image_url = "/data/potion.png"
    await TurnStateApplier(manager)._prepare_inventory_items(event, False)
    expected = ("POTION", "POTION") if replacement else ("POTION_COPY_2", "POTION_COPY_3")
    assert (event.new_inventory_items[0].id, event.spawned_items[0].id) == expected
    assert event.new_inventory_items[0].image_url == "/data/potion.png"


async def test_entity_update_with_empty_values_persists_without_later_dirty_stages(setup_test_db):
    async with TestSessionLocal() as db:
        user, _adventure, _avatar, state = await _seed_game_context(db)
        db.add(
            WorldEntity(
                id="NPC",
                session_id=state.session_id,
                entity_type="NPC",
                name="Guard",
                description="A guard",
                current_scene_id="START",
                inventory=[],
            )
        )
        state.entity_states = {"NPC": {"notes": "old", "is_hidden": True, "hp": 10}}
        await db.commit()
        manager = GameTurnManager(db, state.session_id, user)
        await manager.initialize()
        event = GameEvent(
            updated_entities=[
                WorldEntityUpdate(
                    entity_id="NPC",
                    notes="",
                    is_hidden=False,
                    hp=0,
                    inventory=[],
                )
            ]
        )
        await manager._apply_game_event(event)
        await db.commit()
        await db.refresh(state)
        assert state.entity_states["NPC"]["notes"] == ""
        assert state.entity_states["NPC"]["is_hidden"] is False
        assert state.entity_states["NPC"]["hp"] == 0
        assert state.entity_states["NPC"]["inventory"] == []


async def test_late_event_failure_can_roll_back_earlier_avatar_mutation(setup_test_db, monkeypatch):
    async with TestSessionLocal() as db:
        user, _adventure, avatar, state = await _seed_game_context(db)
        manager = GameTurnManager(db, state.session_id, user)
        await manager.initialize()
        old_hp = avatar.hp
        monkeypatch.setattr(
            manager,
            "_apply_adventure_generator_tools",
            AsyncMock(side_effect=RuntimeError("failed")),
        )
        with pytest.raises(RuntimeError, match="failed"):
            await manager._apply_game_event(GameEvent(hp_change=-10))
        assert avatar.hp == old_hp - 10
        await db.rollback()
        await db.refresh(avatar)
        assert avatar.hp == old_hp
