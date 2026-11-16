"""Transfer known instances once while retaining independent consumable grants."""

from copy import deepcopy
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import select

from backend.engine.rule_engine import GameEvent, InventoryItem, WorldEntityUpdate
from backend.engine.visual_novel.continuity import PLAYER, possession_snapshot
from backend.models.avatar import Avatar
from backend.models.session_state import SessionState
from backend.models.world_entity import WorldEntity
from tests.conftest import TestSessionLocal
from tests.inventory_transfer_support import POTION, potion_row, seed_manager
from tests.llm_fakes import RoleLLMFactory

pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize("template", [False, True])
async def test_first_scene_consumable_transfer_keeps_canonical_id_and_metadata(template):
    async with TestSessionLocal() as db:
        manager = await seed_manager(db)
        source = potion_row(manager, template=template)
        db.add(source)
        await db.commit()
        event = GameEvent(
            new_inventory_items=[
                InventoryItem(id="POTION", name="Archive tonic", item_type="CONSUMABLE")
            ]
        )
        await manager._apply_game_event(event)
        assert [item["id"] for item in manager.avatar.inventory] == ["POTION"]
        assert all(manager.avatar.inventory[0][key] == value for key, value in POTION.items())
        manager.avatar.inventory[0]["provenance"]["batch"] = "played"
        assert source.metadata_json == POTION
        db.add(
            WorldEntity(
                id="CHEST",
                session_id=manager.game_id,
                entity_type="OBJECT",
                item_type="CONTAINER",
                name="Supply chest",
                description="A chest.",
                current_scene_id="START",
                metadata_json={"locked": True, "item_to_unlock": "POTION"},
            )
        )
        await db.flush()
        unlock = GameEvent(updated_entities=[WorldEntityUpdate(entity_id="CHEST", locked=False)])
        assert (
            await manager._enforce_container_unlock_guardrails(
                unlock, "Use POTION on the supply chest"
            )
            == []
        )
        assert unlock.updated_entities[0].locked is False
        await db.commit()
    async with TestSessionLocal() as db:
        avatar = await db.get(Avatar, "transfer-avatar")
        state = await db.scalar(
            select(SessionState).where(SessionState.session_id == "transfer-session")
        )
        assert avatar.inventory[0]["condition_links"] == POTION["condition_links"]
        assert state.entity_states["POTION"]["is_in_inventory"] is True


async def test_distinct_consumable_grants_keep_quantity_and_reserved_copy_ids():
    async with TestSessionLocal() as db:
        manager = await seed_manager(db, inventory=[POTION])
        db.add(potion_row(manager))
        db.add(
            WorldEntity(
                id="POTION_COPY_1",
                session_id=manager.game_id,
                entity_type="OBJECT",
                item_type="CONSUMABLE",
                name="Reserved tonic",
                description="Another tonic.",
                current_scene_id="START",
            )
        )
        await db.commit()
        event = GameEvent(new_inventory_items=[InventoryItem(**POTION), InventoryItem(**POTION)])
        await manager._apply_game_event(event)
        assert [item["id"] for item in manager.avatar.inventory] == [
            "POTION",
            "POTION_COPY_2",
            "POTION_COPY_3",
        ]


async def test_canonical_pickup_cannot_be_taken_again_through_slash():
    async with TestSessionLocal() as db:
        manager = await seed_manager(db)
        db.add(potion_row(manager))
        await db.commit()
        await manager._apply_game_event(GameEvent(new_inventory_items=[InventoryItem(**POTION)]))
        chunks = [chunk async for chunk in manager.process_turn("/take_direct POTION")]
        assert not any(chunk.startswith("event: error") for chunk in chunks), "".join(chunks)
        assert [item["id"] for item in manager.avatar.inventory] == ["POTION"]
        rows = list(
            await db.scalars(select(WorldEntity).where(WorldEntity.session_id == manager.game_id))
        )
        assert possession_snapshot(manager, rows).owners["POTION"] == PLAYER


@pytest.mark.parametrize("mode", ["rpg", "vn"])
async def test_drop_runtime_possession_materializes_then_can_be_reacquired(mode):
    notebook = {
        **deepcopy(POTION),
        "id": "NOTEBOOK",
        "name": "Archive notebook",
        "item_type": "DEFAULT",
        "metadata_json": {"on_drop_text": "The notebook rests on the desk."},
    }
    async with TestSessionLocal() as db:
        manager = await seed_manager(db, mode=mode, inventory=[notebook])
        chunks = [chunk async for chunk in manager.process_turn("/drop Archive notebook")]
        assert not any(chunk.startswith("event: error") for chunk in chunks), "".join(chunks)
        assert manager.avatar.inventory == []
        row = await db.scalar(
            select(WorldEntity).where(
                WorldEntity.session_id == manager.game_id, WorldEntity.id == "NOTEBOOK"
            )
        )
        assert row is not None
        assert row.current_scene_id == "START"
        assert row.is_in_inventory is False
        assert row.metadata_json["condition_links"] == notebook["condition_links"]
        await db.commit()
    async with TestSessionLocal() as db:
        from backend.api.routes.adventures.gameplay_logic import GameTurnManager
        from backend.models.user import User

        user = await db.scalar(select(User).where(User.username == "transfer-player"))
        manager = GameTurnManager(db, "transfer-session", user)
        chunks = [chunk async for chunk in manager.process_turn("/take_direct NOTEBOOK")]
        assert not any(chunk.startswith("event: error") for chunk in chunks), "".join(chunks)
        assert len(manager.avatar.inventory) == 1
        assert manager.avatar.inventory[0]["id"] == "NOTEBOOK"
        assert manager.avatar.inventory[0]["provenance"] == notebook["provenance"]


async def test_failed_drop_keeps_item_and_does_not_fire_callback(monkeypatch):
    async with TestSessionLocal() as db:
        manager = await seed_manager(db, mode="vn", inventory=[POTION])
        row = potion_row(manager)
        row.current_scene_id = "INVENTORY"
        row.is_in_inventory = True
        db.add(row)
        await db.commit()
        monkeypatch.setattr(manager, "_spawn_scene_item", AsyncMock(return_value=None))
        callback = AsyncMock()
        monkeypatch.setattr(manager, "_execute_inline_script", callback)
        chunks = [chunk async for chunk in manager.process_turn("/drop Archive tonic")]
        assert manager.avatar.inventory == [POTION]
        assert "You dropped" not in "".join(chunks)
        callback.assert_not_awaited()


async def test_first_consumable_pickup_survives_actual_mechanics_turn_and_reload(monkeypatch):
    async with TestSessionLocal() as db:
        manager = await seed_manager(db)
        db.add(potion_row(manager))
        await db.commit()
        llm = MagicMock()
        llm.aexecute_complex_task = AsyncMock(
            return_value=GameEvent(
                new_inventory_items=[
                    InventoryItem(id="POTION", name="Archive tonic", item_type="CONSUMABLE")
                ]
            )
        )

        async def narration():
            yield MagicMock(
                choices=[MagicMock(delta=MagicMock(content="The tonic is now in your pack."))]
            )

        llm.stream_simple_task = AsyncMock(return_value=narration())
        monkeypatch.setattr(
            "backend.api.routes.adventures.gameplay_logic.GameMasterLLM",
            RoleLLMFactory(lambda *args, **kwargs: llm),
        )
        chunks = [chunk async for chunk in manager.process_turn("Pick up the Archive tonic.")]
        assert not any(chunk.startswith("event: error") for chunk in chunks), "".join(chunks)
        assert [item["id"] for item in manager.avatar.inventory] == ["POTION"]
    async with TestSessionLocal() as db:
        avatar = await db.get(Avatar, "transfer-avatar")
        assert avatar.inventory[0]["condition_links"] == POTION["condition_links"]
