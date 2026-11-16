"""Deterministic crafting with a complete, owned gameplay session."""

import pytest

from backend.api.routes.adventures.gameplay_logic import GameTurnManager
from backend.engine.rule_engine import GameEvent
from backend.models.adventure_template import AdventureTemplate
from backend.models.avatar import Avatar
from backend.models.game_session import GameSession
from backend.models.session_state import SessionState
from backend.models.user import User
from backend.models.world_entity import WorldEntity

pytestmark = pytest.mark.asyncio


async def _seed(db):
    user = User(username="player1", hashed_password="pw", role="user")
    db.add(user)
    await db.flush()
    adv = AdventureTemplate(
        id="adv-1", title="Test", owner_id=user.id, time_per_turn=5, strict_rules=True
    )
    db.add(adv)
    await db.flush()
    avatar = Avatar(
        id="av-1",
        template_id=adv.id,
        user_id=user.id,
        name="Hero",
        role="Warrior",
        hp=100,
        stats={"strength": 10, "dexterity": 10},
    )
    db.add(avatar)
    await db.flush()
    db.add(GameSession(id="session-1", user_id=user.id, template_id=adv.id, avatar_id=avatar.id))
    await db.flush()
    state = SessionState(
        session_id="session-1",
        template_id=adv.id,
        avatar_id=avatar.id,
        user_id=user.id,
        current_scene_id="START",
        in_game_time=0,
    )
    db.add(state)
    await db.commit()
    return user, adv, avatar, state


async def test_constructable_materializes_when_all_ingredients_combined(setup_test_db):
    from tests.conftest import TestSessionLocal

    async with TestSessionLocal() as db:
        user, _adv, avatar, state = await _seed(db)

        # Two ingredients in the player's inventory.
        db.add(
            WorldEntity(
                id="BATTERY",
                session_id=state.session_id,
                entity_type="OBJECT",
                item_type="DEFAULT",
                name="Battery",
                description="A battery.",
                current_scene_id="START",
                is_hidden=False,
                is_in_inventory=True,
            )
        )
        db.add(
            WorldEntity(
                id="TORCH",
                session_id=state.session_id,
                entity_type="OBJECT",
                item_type="DEFAULT",
                name="Torch",
                description="A torch.",
                current_scene_id="START",
                is_hidden=False,
                is_in_inventory=True,
            )
        )
        # Hidden constructable result.
        db.add(
            WorldEntity(
                id="LANTERN",
                session_id=state.session_id,
                entity_type="OBJECT",
                item_type="CONSTRUCTABLE",
                name="Lantern",
                description="A lantern.",
                current_scene_id="START",
                is_hidden=True,
                combination_ingredients=["BATTERY", "TORCH"],
            )
        )
        await db.commit()

        avatar.inventory = [
            {"id": "BATTERY", "name": "Battery"},
            {"id": "TORCH", "name": "Torch"},
        ]
        await db.commit()

        manager = GameTurnManager(db, state.session_id, user)
        assert await manager.initialize()

        event = GameEvent(combination_intent=True)
        messages = await manager._enforce_constructable_combination(
            event, "combine battery with torch"
        )

        assert any("create" in m.lower() for m in messages)
        # Ingredients scheduled for removal from inventory.
        assert set(event.removed_inventory_item_ids or []) == {"BATTERY", "TORCH"}
        # Constructable revealed in current scene.
        reveal = next(u for u in event.updated_entities if u.entity_id == "LANTERN")
        assert reveal.is_hidden is False
        assert any(
            m.entity_id == "LANTERN" and m.to_scene_id == "START"
            for m in (event.moved_entities or [])
        )


async def test_constructable_noop_when_ingredient_missing(setup_test_db):
    from tests.conftest import TestSessionLocal

    async with TestSessionLocal() as db:
        user, _adv, avatar, state = await _seed(db)

        db.add(
            WorldEntity(
                id="BATTERY",
                session_id=state.session_id,
                entity_type="OBJECT",
                item_type="DEFAULT",
                name="Battery",
                description="A battery.",
                current_scene_id="START",
                is_hidden=False,
                is_in_inventory=True,
            )
        )
        db.add(
            WorldEntity(
                id="TORCH",
                session_id=state.session_id,
                entity_type="OBJECT",
                item_type="DEFAULT",
                name="Torch",
                description="A torch.",
                current_scene_id="START",
                is_hidden=False,
                is_in_inventory=True,
            )
        )
        db.add(
            WorldEntity(
                id="LANTERN",
                session_id=state.session_id,
                entity_type="OBJECT",
                item_type="CONSTRUCTABLE",
                name="Lantern",
                description="A lantern.",
                current_scene_id="START",
                is_hidden=True,
                combination_ingredients=["BATTERY", "TORCH"],
            )
        )
        await db.commit()

        # Player only carries one of two ingredients.
        avatar.inventory = [{"id": "BATTERY", "name": "Battery"}]
        await db.commit()

        manager = GameTurnManager(db, state.session_id, user)
        assert await manager.initialize()

        event = GameEvent(combination_intent=True)
        messages = await manager._enforce_constructable_combination(
            event, "combine battery with torch"
        )

        assert messages == []
        assert not event.removed_inventory_item_ids
        assert not event.updated_entities


async def test_constructable_noop_when_already_revealed(setup_test_db):
    from tests.conftest import TestSessionLocal

    async with TestSessionLocal() as db:
        user, _adv, avatar, state = await _seed(db)

        db.add(
            WorldEntity(
                id="BATTERY",
                session_id=state.session_id,
                entity_type="OBJECT",
                item_type="DEFAULT",
                name="Battery",
                description="A battery.",
                current_scene_id="START",
                is_hidden=False,
                is_in_inventory=True,
            )
        )
        db.add(
            WorldEntity(
                id="TORCH",
                session_id=state.session_id,
                entity_type="OBJECT",
                item_type="DEFAULT",
                name="Torch",
                description="A torch.",
                current_scene_id="START",
                is_hidden=False,
                is_in_inventory=True,
            )
        )
        # Already visible -> should not re-trigger.
        db.add(
            WorldEntity(
                id="LANTERN",
                session_id=state.session_id,
                entity_type="OBJECT",
                item_type="CONSTRUCTABLE",
                name="Lantern",
                description="A lantern.",
                current_scene_id="START",
                is_hidden=False,
                combination_ingredients=["BATTERY", "TORCH"],
            )
        )
        await db.commit()

        avatar.inventory = [
            {"id": "BATTERY", "name": "Battery"},
            {"id": "TORCH", "name": "Torch"},
        ]
        await db.commit()

        manager = GameTurnManager(db, state.session_id, user)
        assert await manager.initialize()

        event = GameEvent(combination_intent=True)
        messages = await manager._enforce_constructable_combination(
            event, "combine battery with torch"
        )

        assert messages == []
        assert not event.removed_inventory_item_ids


async def test_constructable_noop_without_combine_intent(setup_test_db):
    from tests.conftest import TestSessionLocal

    async with TestSessionLocal() as db:
        user, _adv, avatar, state = await _seed(db)

        db.add(
            WorldEntity(
                id="BATTERY",
                session_id=state.session_id,
                entity_type="OBJECT",
                item_type="DEFAULT",
                name="Battery",
                description="A battery.",
                current_scene_id="START",
                is_hidden=False,
                is_in_inventory=True,
            )
        )
        db.add(
            WorldEntity(
                id="TORCH",
                session_id=state.session_id,
                entity_type="OBJECT",
                item_type="DEFAULT",
                name="Torch",
                description="A torch.",
                current_scene_id="START",
                is_hidden=False,
                is_in_inventory=True,
            )
        )
        db.add(
            WorldEntity(
                id="LANTERN",
                session_id=state.session_id,
                entity_type="OBJECT",
                item_type="CONSTRUCTABLE",
                name="Lantern",
                description="A lantern.",
                current_scene_id="START",
                is_hidden=True,
                combination_ingredients=["BATTERY", "TORCH"],
            )
        )
        await db.commit()

        avatar.inventory = [
            {"id": "BATTERY", "name": "Battery"},
            {"id": "TORCH", "name": "Torch"},
        ]
        await db.commit()

        manager = GameTurnManager(db, state.session_id, user)
        assert await manager.initialize()

        event = GameEvent()
        # Unrelated action — must not trigger construction even though ingredients are carried.
        messages = await manager._enforce_constructable_combination(event, "look around the room")

        assert messages == []
        assert not event.removed_inventory_item_ids


async def test_constructable_consumes_scene_ingredient(setup_test_db):
    from tests.conftest import TestSessionLocal

    async with TestSessionLocal() as db:
        user, _adv, avatar, state = await _seed(db)

        # One ingredient in inventory, one visible in the scene.
        db.add(
            WorldEntity(
                id="BATTERY",
                session_id=state.session_id,
                entity_type="OBJECT",
                item_type="DEFAULT",
                name="Battery",
                description="A battery.",
                current_scene_id="START",
                is_hidden=False,
                is_in_inventory=True,
            )
        )
        db.add(
            WorldEntity(
                id="TORCH",
                session_id=state.session_id,
                entity_type="OBJECT",
                item_type="DEFAULT",
                name="Torch",
                description="A torch.",
                current_scene_id="START",
                is_hidden=False,
                is_in_inventory=False,
            )
        )
        db.add(
            WorldEntity(
                id="LANTERN",
                session_id=state.session_id,
                entity_type="OBJECT",
                item_type="CONSTRUCTABLE",
                name="Lantern",
                description="A lantern.",
                current_scene_id="START",
                is_hidden=True,
                combination_ingredients=["BATTERY", "TORCH"],
            )
        )
        await db.commit()

        avatar.inventory = [{"id": "BATTERY", "name": "Battery"}]
        await db.commit()

        manager = GameTurnManager(db, state.session_id, user)
        assert await manager.initialize()

        event = GameEvent(combination_intent=True)
        messages = await manager._enforce_constructable_combination(event, "use battery on torch")

        assert any("create" in m.lower() for m in messages)
        # Inventory ingredient removed.
        assert event.removed_inventory_item_ids == ["BATTERY"]
        # Scene ingredient hidden.
        torch_update = next(u for u in event.updated_entities if u.entity_id == "TORCH")
        assert torch_update.is_hidden is True
        # Result revealed.
        reveal = next(u for u in event.updated_entities if u.entity_id == "LANTERN")
        assert reveal.is_hidden is False


async def test_constructable_reverts_illegal_spawn(setup_test_db):
    from tests.conftest import TestSessionLocal

    async with TestSessionLocal() as db:
        user, _adv, avatar, state = await _seed(db)

        db.add(
            WorldEntity(
                id="BATTERY",
                session_id=state.session_id,
                entity_type="OBJECT",
                item_type="DEFAULT",
                name="Battery",
                description="A battery.",
                current_scene_id="START",
                is_hidden=False,
                is_in_inventory=True,
            )
        )
        db.add(
            WorldEntity(
                id="TORCH",
                session_id=state.session_id,
                entity_type="OBJECT",
                item_type="DEFAULT",
                name="Torch",
                description="A torch.",
                current_scene_id="START",
                is_hidden=False,
                is_in_inventory=True,
            )
        )
        db.add(
            WorldEntity(
                id="LANTERN",
                session_id=state.session_id,
                entity_type="OBJECT",
                item_type="CONSTRUCTABLE",
                name="Lantern",
                description="A lantern.",
                current_scene_id="START",
                is_hidden=True,
                combination_ingredients=["BATTERY", "TORCH"],
            )
        )
        await db.commit()

        manager = GameTurnManager(db, state.session_id, user)
        assert await manager.initialize()

        # The LLM outputs schema updates trying to illegally add/unhide the lantern.
        from backend.engine.rule_engine import InventoryItem, WorldEntityUpdate

        event = GameEvent(
            new_inventory_items=[InventoryItem(id="LANTERN", name="Lantern")],
            updated_entities=[WorldEntityUpdate(entity_id="LANTERN", is_hidden=False)],
        )

        messages = await manager._enforce_constructable_combination(event, "look at lantern")

        # The lantern should be removed from new_inventory_items and updated_entities updates.
        assert not event.new_inventory_items
        assert not event.updated_entities
        assert any("Rule Violation" in m for m in messages)


async def test_constructable_crafts_in_any_language_when_gm_flags_intent(setup_test_db):
    """No keyword lists: a French adventure crafts as soon as the GM flags combination_intent."""
    from tests.conftest import TestSessionLocal

    async with TestSessionLocal() as db:
        # Arrange
        user, _adv, avatar, state = await _seed(db)
        db.add(
            WorldEntity(
                id="PILE",
                session_id=state.session_id,
                entity_type="OBJECT",
                item_type="DEFAULT",
                name="Pile",
                description="Une pile.",
                current_scene_id="START",
                is_hidden=False,
                is_in_inventory=True,
            )
        )
        db.add(
            WorldEntity(
                id="TORCHE",
                session_id=state.session_id,
                entity_type="OBJECT",
                item_type="DEFAULT",
                name="Torche",
                description="Une torche.",
                current_scene_id="START",
                is_hidden=False,
                is_in_inventory=True,
            )
        )
        db.add(
            WorldEntity(
                id="LANTERNE",
                session_id=state.session_id,
                entity_type="OBJECT",
                item_type="CONSTRUCTABLE",
                name="Lanterne",
                description="Une lanterne.",
                current_scene_id="START",
                is_hidden=True,
                combination_ingredients=["PILE", "TORCHE"],
            )
        )
        avatar.inventory = [{"id": "PILE", "name": "Pile"}, {"id": "TORCHE", "name": "Torche"}]
        await db.commit()
        manager = GameTurnManager(db, state.session_id, user)
        assert await manager.initialize()

        # Act
        crafted = await manager._enforce_constructable_combination(
            GameEvent(combination_intent=True), "j'assemble la pile avec la torche"
        )
        not_flagged = await manager._enforce_constructable_combination(
            GameEvent(combination_intent=False), "j'assemble la pile avec la torche"
        )

        # Assert
        assert any("Lanterne" in m for m in crafted)
        assert not any("Lanterne" in m for m in not_flagged)
