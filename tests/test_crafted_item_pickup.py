"""Crafted instances retain ordinary pickup rights on later turns."""

import pytest
from sqlalchemy import select

from backend.engine.rule_engine import GameEvent, InventoryItem
from backend.models.avatar import Avatar
from backend.models.world_entity import WorldEntity
from tests.conftest import TestSessionLocal
from tests.inventory_transfer_support import seed_manager

pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize("hidden_override", [False, None])
async def test_crafted_scene_item_can_be_taken_on_next_event_after_reload(hidden_override):
    async with TestSessionLocal() as db:
        manager = await seed_manager(db)
        for identifier in ("BATTERY", "BULB"):
            db.add(
                WorldEntity(
                    id=identifier,
                    session_id=manager.game_id,
                    entity_type="OBJECT",
                    name=identifier.title(),
                    description="A component.",
                    current_scene_id="START",
                    is_hidden=False,
                )
            )
        db.add(
            WorldEntity(
                id="LANTERN",
                session_id=manager.game_id,
                entity_type="OBJECT",
                item_type="CONSTRUCTABLE",
                name="Lantern",
                description="A workshop lantern.",
                current_scene_id="START",
                is_hidden=True,
                image_url="/data/fixture-lantern.png",
                combination_ingredients=["BATTERY", "BULB"],
            )
        )
        await db.commit()
        event = GameEvent(combination_intent=True)
        messages = await manager._enforce_constructable_combination(
            event, "Combine battery and bulb"
        )
        assert any("create" in message for message in messages)
        await manager._apply_game_event(event)
        if hidden_override is None:
            row = await db.scalar(
                select(WorldEntity).where(
                    WorldEntity.session_id == manager.game_id, WorldEntity.id == "LANTERN"
                )
            )
            row.is_hidden = False
            states = dict(manager.state.entity_states)
            states["LANTERN"] = {
                key: value for key, value in states["LANTERN"].items() if key != "is_hidden"
            }
            manager.state.entity_states = states
        await db.commit()
    async with TestSessionLocal() as db:
        from backend.api.routes.adventures.gameplay_logic import GameTurnManager
        from backend.models.user import User

        user = await db.scalar(select(User).where(User.username == "transfer-player"))
        manager = GameTurnManager(db, "transfer-session", user)
        assert await manager.initialize()
        pickup = GameEvent(
            new_inventory_items=[
                InventoryItem(id="LANTERN", name="Lantern", item_type="CONSTRUCTABLE")
            ]
        )
        messages = await manager._enforce_constructable_combination(pickup, "Take the lantern")
        assert messages == []
        assert [item.id for item in pickup.new_inventory_items] == ["LANTERN"]
        await manager._apply_game_event(pickup)
        await db.commit()
    async with TestSessionLocal() as db:
        avatar = await db.get(Avatar, "transfer-avatar")
        assert [item["id"] for item in avatar.inventory] == ["LANTERN"]
