"""Unknown item IDs must not become persisted facts or successful UI outcomes."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import select

from backend.api.routes.adventures.gameplay_logic import GameTurnManager
from backend.api.routes.adventures.turn_prompt_layout import build_outcome_json
from backend.engine.mutation_targets import TargetIndex, validate_mutation_targets
from backend.engine.rule_engine import GameEvent
from backend.models.chat import ChatMessage
from backend.models.world_entity import WorldEntity
from tests.conftest import TestSessionLocal
from tests.llm_fakes import RoleLLMFactory
from tests.test_game_loop import _seed_game_context

pytestmark = pytest.mark.asyncio


async def _manager(db, mode):
    user, adventure, avatar, state = await _seed_game_context(db)
    adventure.rule_enforcement_mode = mode
    adventure.strict_rules = mode == "strict"
    avatar.inventory = [
        {"id": "FRACTURE_LOG", "name": "Осколок журнала", "description": "A real item"}
    ]
    state.world_memories = [
        {"id": "old", "description": "An earlier true fact", "emotion": "neutral"}
    ]
    db.add(
        WorldEntity(
            id="DOOR",
            name="Старая дверь",
            description="Closed",
            entity_type="OBJECT",
            session_id=state.session_id,
            template_id=adventure.id,
            current_scene_id="START",
        )
    )
    await db.commit()
    manager = GameTurnManager(db, state.session_id, user)
    await manager.initialize()
    return manager


def _ghost_event():
    return GameEvent.model_validate(
        {
            "removed_inventory_item_ids": ["SHARD_01"],
            "updated_inventory_items": [{"id": "SHARD_01", "name": "Ash"}],
            "updated_entities": [
                {"entity_id": "SHARD_01", "description": "Destroyed"},
                {"entity_id": "DOOR", "description": "Open"},
            ],
            "deleted_entities": ["SHARD_01"],
            "new_world_memories": [{"description": "The shard was consumed forever."}],
            "remember_notes": ["The shard is destroyed."],
            "forget_notes": ["An earlier true fact"],
            "clear_notes": True,
            "narrative_description": "The shard is gone forever.",
        }
    )


@pytest.mark.parametrize("mode", ["strict", "story", "chat", "vn"])
async def test_applier_rejects_unknown_targets_and_false_memories(setup_test_db, mode):
    async with TestSessionLocal() as db:
        manager = await _manager(db, mode)
        event = _ghost_event()
        messages = await manager._apply_game_event(event)
        await db.flush()

        assert manager.avatar.inventory[0]["id"] == "FRACTURE_LOG"
        assert "SHARD_01" not in manager.state.entity_states
        assert manager.state.entity_states["DOOR"]["description"] == "Open"
        assert manager.state.world_memories == [
            {"id": "old", "description": "An earlier true fact", "emotion": "neutral"}
        ]
        assert not event.new_world_memories and not event.remember_notes
        assert not event.forget_notes and not event.clear_notes
        assert not event.removed_inventory_item_ids and not event.updated_inventory_items
        assert not event.deleted_entities
        draft, outcome = build_outcome_json(event)
        assert "NOT executed" in draft
        assert "SHARD_01" not in outcome
        assert "gone forever" not in draft
        assert not any("consumed" in message for message in messages)


async def test_canonical_ids_names_and_explicit_new_items_remain_supported(setup_test_db):
    async with TestSessionLocal() as db:
        manager = await _manager(db, "chat")
        event = GameEvent.model_validate(
            {
                "removed_inventory_item_ids": ["FRACTURE_LOG", "fracture_log", " осколок журнала "],
                "updated_entities": [{"entity_id": "старая дверь", "description": "Open"}],
                "new_inventory_items": [{"id": "NEW_TOKEN", "name": "A new token"}],
                "spawned_items": [{"id": "NEW_FLOWER", "name": "A flower"}],
                "narrative_description": "The shard was given away.",
                "new_world_memories": [{"description": "The shard was given away."}],
            }
        )
        await manager._apply_game_event(event)
        assert event.removed_inventory_item_ids == ["FRACTURE_LOG"]
        assert event.updated_entities[0].entity_id == "DOOR"
        assert {item["id"] for item in manager.avatar.inventory} == {"NEW_TOKEN"}
        assert manager.state.world_memories[-1]["description"] == "The shard was given away."
        assert event.narrative_description == "The shard was given away."


async def test_chat_turn_does_not_emit_fake_removed_notification(setup_test_db, monkeypatch):
    async with TestSessionLocal() as db:
        manager = await _manager(db, "chat")
        llm = MagicMock(model="local-test", provider="openai")

        async def structured(*args, **kwargs):
            schema = kwargs.get("response_model") or args[2]
            return schema.model_validate(_ghost_event().model_dump())

        async def stream(*args, **kwargs):
            yield MagicMock(
                choices=[MagicMock(delta=MagicMock(content="The item remains with you."))]
            )

        llm.aexecute_complex_task = AsyncMock(side_effect=structured)

        async def return_stream(*args, **kwargs):
            return stream(*args, **kwargs)

        llm.stream_simple_task = AsyncMock(side_effect=return_stream)
        monkeypatch.setattr(
            "backend.api.routes.adventures.gameplay_logic.GameMasterLLM",
            RoleLLMFactory(lambda *args, **kwargs: llm),
        )
        chunks = [
            chunk async for chunk in manager.process_turn("I destroy the shard in my inventory.")
        ]
        assert "Removed SHARD_01" not in "".join(chunks)
        assert "Updated Ash" not in "".join(chunks)
        prompt = str(llm.stream_simple_task.call_args.kwargs["messages"])
        assert "NOT executed" in prompt
        assert manager.avatar.inventory[0]["id"] == "FRACTURE_LOG"
        chats = (
            (await db.execute(select(ChatMessage).where(ChatMessage.role == "system")))
            .scalars()
            .all()
        )
        assert not any(
            "Removed SHARD_01" in chat.content or "consumed forever" in chat.content
            for chat in chats
        )


async def test_exact_id_wins_and_ambiguous_case_or_names_are_rejected():
    index = TargetIndex(
        [
            {"id": "TOKEN", "name": "Token"},
            {"id": "token", "name": "Token"},
            {"id": "SINGLE", "name": "Осколок"},
        ]
    )
    assert index.resolve("TOKEN") == "TOKEN"
    assert index.resolve("token") == "token"
    assert index.resolve("ToKeN") is None
    assert index.resolve("single") == "SINGLE"
    assert index.resolve("осколок") == "SINGLE"
    assert index.resolve("Shard") is None


@pytest.mark.parametrize("ownership", ["entity", "snapshot", "asset", "no_template"])
async def test_deleted_template_and_foreign_objects_cannot_be_mutated(setup_test_db, ownership):
    async with TestSessionLocal() as db:
        manager = await _manager(db, "chat")
        if ownership != "entity":
            door = await db.scalar(select(WorldEntity).where(WorldEntity.id == "DOOR"))
            await db.delete(door)
        if ownership == "snapshot":
            manager.state.entity_states = {"__manifest_snapshot__": {}}
        if ownership == "asset":
            manager.state.entity_states = {"__asset_snapshot__": {}}
        if ownership == "no_template":
            manager.state.template_id = None
        db.add_all(
            [
                WorldEntity(
                    id="DELETED",
                    name="Deleted",
                    description="Gone",
                    current_scene_id="START",
                    entity_type="OBJECT",
                    template_id="adv-1",
                ),
                WorldEntity(
                    id="ORPHAN",
                    name="Orphan",
                    description="Unowned",
                    current_scene_id="START",
                    entity_type="OBJECT",
                ),
                WorldEntity(
                    id="FOREIGN",
                    name="Foreign",
                    description="Elsewhere",
                    current_scene_id="START",
                    entity_type="OBJECT",
                    session_id="other-session",
                ),
            ]
        )
        await db.flush()
        event = GameEvent(
            updated_entities=[
                {"entity_id": item_id, "description": "Destroyed"}
                for item_id in ("DELETED", "ORPHAN", "FOREIGN")
            ]
        )
        rejected = await validate_mutation_targets(manager, event)
        assert len(rejected) == 3
        assert not event.updated_entities


async def test_same_event_new_items_and_malformed_legacy_override(setup_test_db):
    async with TestSessionLocal() as db:
        manager = await _manager(db, "chat")
        manager.state.entity_states = {"DOOR": "legacy invalid entry"}
        event = GameEvent(
            new_inventory_items=[{"id": "NEW", "name": "New token"}],
            spawned_items=[{"id": "FLOWER", "name": "Flower"}],
            updated_entities=[{"entity_id": "FLOWER", "description": "Red"}],
            removed_inventory_item_ids=["new"],
        )
        assert await validate_mutation_targets(manager, event) == []
        assert event.removed_inventory_item_ids == ["NEW"]
        assert event.updated_entities[0].entity_id == "FLOWER"
