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
from tests.test_vn_turn_integration import TurnRoles, install_roles, seed_vn


@pytest.mark.asyncio
async def test_completed_gift_is_saved_once_and_not_worn(monkeypatch):
    narration = "Лина передала герою шарф, и он убрал его в сумку."
    monkeypatch.setattr("tests.test_vn_turn_integration.NARRATION", narration)

    class GiftRoles(TurnRoles):
        async def structured(self, *args, **kwargs):
            schema = kwargs.get("response_model") or args[2]
            if schema is ItemExtraction:
                return ItemExtraction(
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
                    ]
                )
            return await super().structured(*args, **kwargs)

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
