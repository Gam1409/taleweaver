"""Created editor callbacks run through the saved game's existing event handlers."""

import pytest
from sqlalchemy import select

from backend.api.routes.adventures.gameplay_logic import GameTurnManager
from backend.engine.rule_engine import GameEvent, WorldEntityUpdate
from backend.models.chat import ChatMessage
from backend.models.session_state import SessionState
from backend.models.user import User
from backend.models.world_entity import WorldEntity
from tests.conftest import TestSessionLocal
from tests.editor_entity_creation_support import (
    ITEM_EVENTS,
    NPC_EVENTS,
    entity_creation_world,
    entity_payload,
    event_fields,
)

__all__ = ["entity_creation_world"]
pytestmark = pytest.mark.asyncio


async def _start_created_entity(world, kind):
    payload = entity_payload(kind)
    if kind == "OBJECT":
        payload["name"] = "Travel tunic"
    else:
        payload["on_defeat_script"] = "tw.system('Defeat script executed.')"
    created = await world.client.post(
        f"/api/adventures/{world.template_id}/editor/entity", json=payload
    )
    assert created.status_code == 200, created.text
    started = await world.client.post(f"/api/adventures/{world.template_id}/sessions/start")
    assert started.status_code == 201, started.text
    return started.json()["game_id"]


async def _manager(db, world, game_id):
    user = await db.get(User, world.user_id)
    manager = GameTurnManager(db, game_id, user)
    assert await manager.initialize()
    assert manager.state.current_scene_id == "YARD"
    await manager._apply_game_event(GameEvent(new_scene_id="HALL"))
    assert manager.state.current_scene_id == "HALL"
    entity = await db.scalar(select(WorldEntity).where(WorldEntity.session_id == game_id))
    assert entity.spatial_position == "beside the archive door"
    return manager


async def _assert_saved_callbacks(game_id, prefixes, kind):
    async with TestSessionLocal() as db:
        state = await db.scalar(select(SessionState).where(SessionState.session_id == game_id))
        variables = (state.entity_states or {}).get("__script_vars__", {})
        assert {prefix: variables.get(prefix) for prefix in prefixes} == {
            prefix: 1 for prefix in prefixes
        }
        messages = list(
            await db.scalars(select(ChatMessage.content).where(ChatMessage.session_id == game_id))
        )
        for key, text in event_fields(kind).items():
            if key.endswith("_text"):
                assert messages.count(text) == 1
        entity = await db.scalar(
            select(WorldEntity).where(
                WorldEntity.session_id == game_id,
                WorldEntity.entity_type == kind,
            )
        )
        assert entity.spatial_position == ("beside the archive door" if kind == "NPC" else None)


async def test_created_item_callbacks_execute_on_real_inventory_commands(
    entity_creation_world, monkeypatch
):
    world = entity_creation_world
    game_id = await _start_created_entity(world, "OBJECT")

    async def no_inference(*args, **kwargs):
        raise AssertionError("Inventory commands must not request inference")
        yield ""

    monkeypatch.setattr(GameTurnManager, "_run_llm_cycle", no_inference)
    async with TestSessionLocal() as db:
        manager = await _manager(db, world, game_id)
        for command in (
            "/take_direct COAT",
            "/equip Travel tunic",
            "/unequip Chest",
            "/drop Travel tunic",
        ):
            chunks = [chunk async for chunk in manager.process_turn(command)]
            assert not any(chunk.startswith("event: error") for chunk in chunks), "".join(chunks)
        await db.commit()
    await _assert_saved_callbacks(game_id, ITEM_EVENTS, "OBJECT")


async def test_created_npc_callbacks_execute_on_arrival_and_defeat(entity_creation_world):
    world = entity_creation_world
    game_id = await _start_created_entity(world, "NPC")
    async with TestSessionLocal() as db:
        manager = await _manager(db, world, game_id)
        messages = await manager._apply_game_event(
            GameEvent(updated_entities=[WorldEntityUpdate(entity_id="GUIDE", is_defeated=True)])
        )
        assert "Defeat script executed." in messages
        await db.commit()
    await _assert_saved_callbacks(game_id, (NPC_EVENTS[1],), "NPC")
    async with TestSessionLocal() as db:
        messages = list(
            await db.scalars(select(ChatMessage.content).where(ChatMessage.session_id == game_id))
        )
        assert messages.count("Defeat script executed.") == 1
