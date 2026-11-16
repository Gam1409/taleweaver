"""A completed narrated transfer reaches the actual saved session and system messages."""

import json

import pytest
from sqlalchemy import select

from backend.api.routes.adventures.gameplay_logic import GameTurnManager
from backend.engine.narrated_items.runtime import KEY
from backend.engine.narrated_items.schema import ItemAction, ItemExtraction
from backend.engine.visual_novel.continuity import PLAYER
from backend.models.avatar import Avatar
from backend.models.chat import ChatMessage
from backend.models.world_entity import WorldEntity
from tests.conftest import TestSessionLocal
from tests.state_response_fixture import extraction
from tests.test_vn_turn_integration import TurnRoles, install_roles, seed_vn


@pytest.mark.asyncio
@pytest.mark.parametrize("pending_candidate", [False, True])
async def test_completed_gift_is_saved_once_and_not_worn(monkeypatch, pending_candidate):
    narration = "Лина передала герою шарф, и он убрал его в сумку."
    monkeypatch.setattr("tests.test_vn_turn_integration.NARRATION", narration)

    class GiftRoles(TurnRoles):
        async def structured(self, *args, **kwargs):
            schema = kwargs.get("response_model") or args[2]
            if issubclass(schema, ItemExtraction):
                return extraction(
                    schema,
                    actions=[
                        ItemAction(
                            source_owner="LINA",
                            destination_owner=PLAYER,
                            disposition="carried",
                            evidence=narration,
                            basis="completed",
                            new_item={
                                "name": "Шарф",
                                "description": "Шарф, полученный от Лины. Остальные детали не установлены.",
                                "kind": "clothing",
                                "clothing": {"layer": 2, "coverage": ["torso"]},
                                "wearable_slots": ["Neck"],
                            },
                        )
                    ],
                )
            result = await super().structured(*args, **kwargs)
            if pending_candidate and schema.__name__.startswith("VNProgressionIntent"):
                payload = result.model_dump()
                payload["new_inventory_items"] = [
                    {"id": "MODEL_SCARF", "name": "Шарф", "item_type": "WEARABLE"}
                ]
                return schema.model_validate(payload)
            return result

    roles = GiftRoles()
    install_roles(monkeypatch, roles)
    async with TestSessionLocal() as db:
        user, avatar, state, _ = await seed_vn(db)
        npc = await db.scalar(select(WorldEntity).where(WorldEntity.id == "LINA"))
        original_inventory = list(npc.inventory)
        manager = GameTurnManager(db, "session-1", user)
        chunks = [chunk async for chunk in manager.process_turn("Спасибо за шарф.")]
        assert not any(chunk.startswith("event: error") for chunk in chunks), "".join(chunks)
        assert any(
            "Шарф" in json.loads(chunk.split("data: ", 1)[1])["content"]
            for chunk in chunks
            if chunk.startswith("event: system")
        )
        await db.refresh(avatar)
        gifts = [item for item in avatar.inventory if item["name"] == "Шарф"]
        assert len(gifts) == 1
        assert gifts[0]["clothing"]["layer"] == 2
        assert not any(
            value and value.get("id") == gifts[0]["id"]
            for value in (avatar.equipment or {}).values()
        )
        assert state.entity_states["LINA"]["inventory"] == original_inventory
        assert state.entity_states[KEY]["status"] == "complete"
        avatar_id = avatar.id
        system_messages = list(
            await db.scalars(
                select(ChatMessage).where(
                    ChatMessage.session_id == "session-1", ChatMessage.role == "system"
                )
            )
        )
        assert any("Шарф" in message.content for message in system_messages)
    async with TestSessionLocal() as db:
        restored = await db.get(Avatar, avatar_id)
        assert len([item for item in restored.inventory if item["name"] == "Шарф"]) == 1


@pytest.mark.asyncio
async def test_rejected_item_does_not_discard_narrator_thoughts_or_emotions(monkeypatch):
    from backend.engine.npc_presentation.settings import KEY as PORTRAIT_KEY

    body = "Лина оставила шарф у себя."
    cue = {
        "npc_id": "LINA",
        "emotion": "determination",
        "intensity": 73,
        "thought": "Я его сохраню.",
    }
    footer = "<npc-state>" + json.dumps({"npcs": [cue]}) + "</npc-state>"
    monkeypatch.setattr("tests.test_vn_turn_integration.NARRATION", body + footer)

    class RejectedGiftRoles(TurnRoles):
        async def structured(self, *args, **kwargs):
            schema = kwargs.get("response_model") or args[2]
            if issubclass(schema, ItemExtraction):
                return extraction(
                    schema,
                    actions=[
                        ItemAction(
                            item_id="UNREGISTERED_SCARF",
                            source_owner="LINA",
                            destination_owner=PLAYER,
                            disposition="carried",
                            evidence=body,
                            basis="completed",
                        )
                    ],
                )
            return await super().structured(*args, **kwargs)

    install_roles(monkeypatch, RejectedGiftRoles())
    async with TestSessionLocal() as db:
        user, avatar, state, _ = await seed_vn(db)
        state.entity_states = {
            **state.entity_states,
            PORTRAIT_KEY: {
                "emotion_palette": True,
                "character_thoughts": True,
                "brightness": 40,
            },
        }
        await db.commit()
        inventory = list(avatar.inventory)
        manager = GameTurnManager(db, "session-1", user)
        events = [event async for event in manager.process_turn("Можно взять шарф?")]
        assert not any(event.startswith("event: error") for event in events), events
        assert any("need review" in event for event in events if event.startswith("event: system"))
        await db.refresh(state)
        assert state.entity_states[KEY]["rejected"] and not state.entity_states[KEY]["accepted"]
        assert avatar.inventory == inventory
        message = await db.scalar(
            select(ChatMessage)
            .where(
                ChatMessage.session_id == state.session_id,
                ChatMessage.role == "assistant",
            )
            .order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc())
        )
        assert message.content == body
        assert message.to_client_dict()["portrait_state"]["npcs"]["LINA"] == {
            key: value for key, value in cue.items() if key != "npc_id"
        }


@pytest.mark.asyncio
async def test_current_wear_description_registers_garment_without_dressing_action(monkeypatch):
    narration = "Лина стоит у окна в синем хлопковом халате."
    monkeypatch.setattr("tests.test_vn_turn_integration.NARRATION", narration)

    class ObservationRoles(TurnRoles):
        async def structured(self, *args, **kwargs):
            schema = kwargs.get("response_model") or args[2]
            if issubclass(schema, ItemExtraction):
                return extraction(
                    schema,
                    actions=[
                        ItemAction(
                            source_owner="LINA",
                            destination_owner="LINA",
                            disposition="worn",
                            evidence=narration,
                            basis="observed_wear",
                            new_item={
                                "name": "Синий халат",
                                "description": "Синий хлопковый халат.",
                                "kind": "clothing",
                                "clothing": {"layer": 2, "coverage": ["torso", "arms"]},
                                "wearable_slots": ["Chest"],
                            },
                        )
                    ],
                )
            return await super().structured(*args, **kwargs)

    install_roles(monkeypatch, ObservationRoles())
    async with TestSessionLocal() as db:
        user, _, state, _ = await seed_vn(db)
        manager = GameTurnManager(db, "session-1", user)
        chunks = [chunk async for chunk in manager.process_turn("Посмотреть на Лину.")]
        assert not any(chunk.startswith("event: error") for chunk in chunks), "".join(chunks)
        await db.refresh(state)
        actor = state.entity_states["LINA"]
        garment = next(item for item in actor["inventory"] if item.get("name") == "Синий халат")
        assert any(row["item_id"] == garment["id"] for row in actor["visual_profile"]["worn"])
        assert state.entity_states[KEY]["rejected"] == []
        assert state.entity_states[KEY]["accepted"][0]["evidence"] == narration
