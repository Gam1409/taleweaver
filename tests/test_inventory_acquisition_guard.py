"""Ordinary mechanics transfers physical instances once, across durable full turns."""

from copy import deepcopy
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import select

from backend.api.routes.adventures.gameplay_logic import GameTurnManager
from backend.core.system_diagnostics import service
from backend.engine.rule_engine import GameEvent, InventoryItem
from backend.engine.visual_novel.continuity import PLAYER, possession_snapshot
from backend.models.adventure_template import AdventureTemplate
from backend.models.avatar import Avatar
from backend.models.user import User
from backend.models.world_entity import WorldEntity
from tests.conftest import TestSessionLocal
from tests.inventory_transfer_support import POTION, potion_row, seed_manager
from tests.llm_fakes import RoleLLMFactory
from tests.state_trace_support import (
    event_payloads,
    isolate_trace_directory,
    trace_files,
    trace_rows,
)

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def isolated_diagnostics(tmp_path, monkeypatch):
    service.set_enabled(False)
    yield from isolate_trace_directory(tmp_path, monkeypatch)


def install_mechanics(monkeypatch, proposals):
    llm = MagicMock()
    llm.aexecute_complex_task = AsyncMock(
        side_effect=[GameEvent(new_inventory_items=[InventoryItem(**item)]) for item in proposals]
    )

    async def narration():
        yield MagicMock(choices=[MagicMock(delta=MagicMock(content="The archive remains quiet."))])

    llm.stream_simple_task = AsyncMock(side_effect=lambda *args, **kwargs: narration())
    monkeypatch.setattr(
        "backend.api.routes.adventures.gameplay_logic.GameMasterLLM",
        RoleLLMFactory(lambda *args, **kwargs: llm),
    )
    monkeypatch.setattr(
        "backend.engine.gameplay.manager.schedule_npc_journal", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(
        "backend.engine.gameplay.manager.schedule_images", lambda *args, **kwargs: None
    )
    return llm


async def full_turn(command, *, allow_dynamic=None):
    async with TestSessionLocal() as db:
        user = await db.scalar(select(User).where(User.username == "transfer-player"))
        manager = GameTurnManager(db, "transfer-session", user)
        chunks = [chunk async for chunk in manager.process_turn(command)]
        assert not any(chunk.startswith("event: error") for chunk in chunks), "".join(chunks)
        assert sum(chunk.startswith("event: final") for chunk in chunks) == 1
        if allow_dynamic is not None:
            assert manager.state.allow_dynamic_items is allow_dynamic
            assert manager.adventure.allow_dynamic_items is allow_dynamic
        rows = list(
            await db.scalars(select(WorldEntity).where(WorldEntity.session_id == manager.game_id))
        )
        snapshot = possession_snapshot(manager, rows)
        return snapshot.owners.get("POTION"), chunks


async def saved_inventory():
    async with TestSessionLocal() as db:
        avatar = await db.get(Avatar, "transfer-avatar")
        return deepcopy(avatar.inventory)


@pytest.mark.parametrize("allow_dynamic", [False, True])
@pytest.mark.parametrize("alias", ["id", "name"])
@pytest.mark.parametrize("trace_enabled", [False, True])
async def test_two_fresh_mechanics_turns_cannot_duplicate_a_physical_pickup(
    monkeypatch, allow_dynamic, alias, trace_enabled
):
    async with TestSessionLocal() as db:
        manager = await seed_manager(db)
        db.add(potion_row(manager))
        manager.state.allow_dynamic_items = allow_dynamic
        adventure = await db.get(AdventureTemplate, manager.state.template_id)
        adventure.allow_dynamic_items = allow_dynamic
        await db.commit()
    repeated = {**POTION, "id": "potion" if alias == "id" else None}
    llm = install_mechanics(monkeypatch, [POTION, repeated, POTION])
    service.set_enabled(True, state_failure_traces=trace_enabled)
    for _ in range(2):
        owner, _chunks = await full_turn(
            "Pick up the archive tonic from the shelf.", allow_dynamic=allow_dynamic
        )
        assert owner == PLAYER
        inventory = await saved_inventory()
        assert [item["id"] for item in inventory] == ["POTION"]
        assert inventory[0]["condition_links"] == POTION["condition_links"]
    assert llm.aexecute_complex_task.await_count == 2
    assert llm.stream_simple_task.await_count == 2
    assert len(trace_files()) == int(trace_enabled)
    if trace_enabled:
        reasons = event_payloads(trace_rows(), "state.rejected")
        rejected = next(reason for reason in reasons if reason["domain"] == "inventory")
        assert rejected["reason_code"] == "inventory.acquisition_already_owned"
        assert rejected["details"]["canonical_item_id"] == "POTION"
        assert rejected["details"]["source"]["owner"] == PLAYER
    await full_turn("/drop Archive tonic")
    assert await saved_inventory() == []
    owner, _chunks = await full_turn(
        "Pick up the archive tonic from the shelf.", allow_dynamic=allow_dynamic
    )
    assert owner == PLAYER
    assert [item["id"] for item in await saved_inventory()] == ["POTION"]
    assert llm.aexecute_complex_task.await_count == 3
    assert llm.stream_simple_task.await_count == 3
    assert len(trace_files()) == int(trace_enabled)


@pytest.mark.parametrize("owner", ["scene", "npc", "container"])
async def test_distinct_same_name_instance_can_transfer_from_another_owner(owner):
    async with TestSessionLocal() as db:
        manager = await seed_manager(db, inventory=[POTION])
        second = {**deepcopy(POTION), "id": "SECOND"}
        row = potion_row(manager)
        row.id = "SECOND"
        row.metadata_json = deepcopy(second)
        row.is_in_inventory = owner != "scene"
        db.add(row)
        if owner != "scene":
            db.add(
                WorldEntity(
                    id="HOLDER",
                    session_id=manager.game_id,
                    entity_type="NPC" if owner == "npc" else "OBJECT",
                    item_type="CONTAINER" if owner == "container" else None,
                    name="Archive holder",
                    description="An accessible holder.",
                    current_scene_id="START",
                    inventory=[second],
                    is_portable=False,
                    metadata_json={"locked": False},
                )
            )
        await db.commit()
        event = GameEvent(new_inventory_items=[InventoryItem(**second)])
        assert await manager._enforce_no_dynamic_item_generation(event) == []
        assert [item.id for item in event.new_inventory_items] == ["SECOND"]
        await manager._apply_game_event(event)
        await db.commit()
    assert [item["id"] for item in await saved_inventory()] == ["POTION", "SECOND"]


async def test_explicit_replacement_and_spawn_reservations_keep_existing_contract():
    async with TestSessionLocal() as db:
        manager = await seed_manager(db, inventory=[POTION])
        db.add(potion_row(manager))
        await db.commit()
        replacement = GameEvent(
            removed_inventory_item_ids=["POTION"], new_inventory_items=[InventoryItem(**POTION)]
        )
        assert await manager._enforce_no_dynamic_item_generation(replacement) == []
        assert [item.id for item in replacement.new_inventory_items] == ["POTION"]
        await manager._apply_game_event(replacement)
        assert [item["id"] for item in manager.avatar.inventory] == ["POTION"]
        spawned = GameEvent(spawned_items=[InventoryItem(**POTION)])
        assert await manager._enforce_no_dynamic_item_generation(spawned) == []
        await manager.state_applier._prepare_inventory_items(spawned, False)
        assert [item.id for item in spawned.spawned_items] == ["POTION_COPY_1"]


async def test_one_mechanics_event_cannot_repeat_the_same_physical_instance():
    async with TestSessionLocal() as db:
        manager = await seed_manager(db)
        db.add(potion_row(manager))
        await db.commit()
        event = GameEvent(new_inventory_items=[InventoryItem(**POTION), InventoryItem(**POTION)])
        reasons = await manager._enforce_no_dynamic_item_generation(event)
        assert reasons
        assert [item.id for item in event.new_inventory_items] == ["POTION"]


@pytest.mark.parametrize("equipment_reference", ["string", "item"])
async def test_equipped_canonical_instance_is_already_owned(equipment_reference):
    async with TestSessionLocal() as db:
        manager = await seed_manager(db)
        row = potion_row(manager)
        row.is_in_inventory = True
        row.current_scene_id = "INVENTORY"
        db.add(row)
        manager.avatar.equipment = {
            "MainHand": "POTION" if equipment_reference == "string" else deepcopy(POTION)
        }
        await db.commit()
        event = GameEvent(new_inventory_items=[InventoryItem(**POTION)])
        assert await manager._enforce_no_dynamic_item_generation(event)
        assert event.new_inventory_items == []
