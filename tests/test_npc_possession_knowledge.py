"""Player knowledge never acts as a live view of an NPC's private possessions."""

import json

from sqlalchemy import select

from backend.api.routes.adventures.gameplay_logic import GameTurnManager
from backend.api.routes.adventures.logic import AdventureLogic
from backend.engine.npc_journal.extract import extraction_context
from backend.engine.npc_journal.records import journal_of, memory_context
from backend.engine.npc_journal.schema import CharacterObservation
from backend.engine.rule_engine import GameEvent, InventoryItem, WorldEntityUpdate
from backend.models.chat import ChatMessage
from backend.models.game_session import GameSession
from backend.models.session_state import SessionState
from backend.models.world_entity import WorldEntity
from tests.conftest import TestSessionLocal
from tests.test_npc_journal import (
    apply,
    introduction,
    journal_world,
    npc_by_id,
    observation,
    portrait_world,
    save_message,
)
from tests.test_npc_logic import _seed_npc_context

__all__ = ["journal_world", "portrait_world"]


async def test_cards_do_not_track_live_possessions_even_when_item_name_is_known(
    auth_client, journal_world
):
    message_id = await save_message("«Меня зовут Мира». Мира показала ключ.")
    npc_id = (
        await apply(
            message_id,
            [
                introduction(
                    observations=[
                        observation(
                            "belongings", "Показала ключ", "Мира показала ключ.", topic="key"
                        )
                    ]
                )
            ],
        )
    )[0]
    path = f"/api/adventures/portrait-session/npcs/{npc_id}"
    before = (await auth_client.get(path)).json()
    async with TestSessionLocal() as db:
        state = await db.scalar(
            select(SessionState).where(SessionState.session_id == "portrait-session")
        )
        state.entity_states = {
            **state.entity_states,
            npc_id: {
                "inventory": [
                    {"id": "SECRET_KEY", "name": "ключ", "description": "Secret code 7391"}
                ]
            },
        }
        await db.commit()
    after = (await auth_client.get(path)).json()
    assert before == after
    assert "inventory" not in after
    directory = (await auth_client.get("/api/adventures/portrait-session/npcs")).json()
    assert "7391" not in json.dumps(directory)
    assert all("inventory" not in npc for npc in directory["characters"])


async def test_scene_payload_hides_npc_possessions_without_mutating_engine_state(journal_world):
    message_id = await save_message()
    npc_id = (await apply(message_id, [introduction()]))[0]
    async with TestSessionLocal() as db:
        npc = await db.scalar(
            select(WorldEntity).where(
                WorldEntity.session_id == "portrait-session", WorldEntity.id == npc_id
            )
        )
        npc.inventory = [{"id": "HIDDEN_GEM", "name": "Hidden gem"}]
        npc.notes = "A SECRET_POCKET holds the gem."
        npc.goal = "SECRET_GOAL: leave before dawn."
        npc.character = "SECRET_CHARACTER: distrusts the visitor."
        npc.hp = 37
        npc.max_hp = 45
        npc.metadata_json = {
            **npc.metadata_json,
            "inventory": [{"id": "NESTED_SECRET"}],
            "loadout": {"equipment": {"ring": "SECRET_RING"}},
            "persona": {"goal": "NESTED_GOAL", "character": "NESTED_CHARACTER"},
        }
        # Some imported saves have stale scene flags on NPC-owned item definitions.
        db.add(
            WorldEntity(
                id="HIDDEN_GEM",
                session_id="portrait-session",
                entity_type="OBJECT",
                name="Hidden gem",
                description="Secret loot",
                current_scene_id="TOWER",
                is_in_inventory=False,
                is_hidden=False,
            )
        )
        await db.commit()
        state = await db.scalar(
            select(SessionState).where(SessionState.session_id == "portrait-session")
        )
        entities = await AdventureLogic.build_session_entities(db, state)
        public = next(e for e in entities if e["id"] == npc_id)
        assert "inventory" not in public
        serialized = json.dumps(public, default=str)
        for secret in (
            "HIDDEN_GEM",
            "NESTED_SECRET",
            "SECRET_RING",
            "SECRET_POCKET",
            "SECRET_GOAL",
            "SECRET_CHARACTER",
            "NESTED_GOAL",
            "NESTED_CHARACTER",
        ):
            assert secret not in serialized
        assert public["hp"] == 37 and public["max_hp"] == 45
        assert "goal" not in public and "character" not in public
        assert "HIDDEN_GEM" not in [e["id"] for e in entities]
        await db.refresh(npc)
        assert npc.inventory[0]["id"] == "HIDDEN_GEM"
        assert npc.goal == "SECRET_GOAL: leave before dawn."
        assert npc.character == "SECRET_CHARACTER: distrusts the visitor."
        assert npc.metadata_json["persona"]["goal"] == "NESTED_GOAL"
        assert npc.metadata_json["loadout"]["equipment"]["ring"] == "SECRET_RING"
        message = await db.get(ChatMessage, message_id)
        session = await db.get(GameSession, "portrait-session")
        payload, _ = await extraction_context(db, message, session)
        assert "HIDDEN_GEM" not in payload and "SECRET_RING" not in payload


async def test_witnessed_item_lifecycle_supersedes_appearance_but_preserves_history(journal_world):
    first = await save_message("«Меня зовут Мира». Мира взяла ваш плащ.")
    npc_id = (
        await apply(
            first,
            [
                introduction(
                    observations=[
                        observation(
                            "belongings",
                            "Получила плащ в подарок",
                            "Мира взяла ваш плащ.",
                            topic="cloak",
                        )
                    ]
                )
            ],
        )
    )[0]
    for category, narration in [
        ("equipment", "Мира надела подаренный плащ."),
        ("belongings", "Мира убрала плащ в сумку."),
        ("belongings", "Мира выбросила плащ."),
    ]:
        message_id = await save_message(narration)
        await apply(
            message_id,
            [
                CharacterObservation(
                    npc_id=npc_id,
                    name="Мира",
                    observations=[observation(category, narration, narration, topic="cloak")],
                )
            ],
        )
    npc = await npc_by_id(npc_id)
    assert len(journal_of(npc)["entries"]) == 4
    for visual_only in (False, True):
        context = memory_context(npc, visual_only=visual_only)
        assert "выбросила" in context
        assert "надела" not in context and "в сумку" not in context
    assert npc.inventory == []  # The journal cannot transfer, create or destroy items.


async def test_engine_gift_storage_and_drop_remain_private_until_narrated(setup_test_db):
    async with TestSessionLocal() as db:
        user, _, avatar, state, npc = await _seed_npc_context(db)
        item = InventoryItem(id="CLOAK", name="Cloak", item_type="WEARABLE")
        avatar.inventory = [item.model_dump(exclude_none=True)]
        db.add(
            WorldEntity(
                id="CLOAK",
                session_id=state.session_id,
                entity_type="OBJECT",
                name="Cloak",
                description="A wool cloak",
                item_type="WEARABLE",
                current_scene_id="KITCHEN",
                is_in_inventory=True,
                is_hidden=False,
            )
        )
        await db.commit()
        manager = GameTurnManager(db, state.session_id, user)
        assert await manager.initialize()
        await manager._apply_game_event(
            GameEvent(
                narrative_description="Marge accepts the cloak and wears it.",
                removed_inventory_item_ids=["CLOAK"],
                updated_entities=[
                    WorldEntityUpdate(
                        entity_id=npc.id, inventory=[item], notes="Wearing the gifted cloak."
                    )
                ],
            )
        )
        await db.commit()
        assert avatar.inventory == []
        assert state.entity_states[npc.id]["inventory"][0]["id"] == "CLOAK"
        await manager._apply_game_event(
            GameEvent(
                narrative_description="Marge stores it.",
                updated_entities=[
                    WorldEntityUpdate(
                        entity_id=npc.id,
                        inventory=[item],
                        notes="The cloak is in her bag, not worn.",
                    )
                ],
            )
        )
        await db.commit()
        public = await AdventureLogic.build_session_entities(db, state)
        assert "inventory" not in next(e for e in public if e["id"] == npc.id)
        assert "CLOAK" not in [e["id"] for e in public]
        await manager._apply_game_event(
            GameEvent(
                narrative_description="Marge discards it.",
                spawned_items=[item],
                updated_entities=[
                    WorldEntityUpdate(
                        entity_id=npc.id, inventory=[], notes="No longer carrying the cloak."
                    )
                ],
            )
        )
        await db.commit()
        assert state.entity_states[npc.id]["inventory"] == []
        public = await AdventureLogic.build_session_entities(db, state)
        assert "CLOAK" in [e["id"] for e in public]
        assert journal_of(npc) == {}  # Mechanics alone do not fabricate learned passages.
