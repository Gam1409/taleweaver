"""Unregistered ordinary items and co-arrivals must survive the mechanics boundary."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from backend.api.routes.adventures.gameplay_logic import GameTurnManager
from backend.api.routes.adventures.state_checks import state_checks
from backend.engine.dynamic_locations.prompts import intent_schema
from backend.engine.dynamic_locations.schema import PlaceProposal, registry
from backend.engine.llm_intents import ChatProgressionIntent
from backend.engine.visual_novel.continuity import prepare_intent
from backend.models.world_entity import WorldEntity
from tests.conftest import TestSessionLocal
from tests.llm_fakes import RoleLLMFactory
from tests.test_dynamic_locations import decision, setup
from tests.test_vn_continuity import entity, manager


def test_unknown_cosmetic_item_is_deferred_not_declared_failed_or_minted():
    owner = manager()
    result = prepare_intent(
        owner,
        {
            "new_inventory_items": [
                {"id": "MODEL_INVENTED", "name": "Scarf", "item_type": "WEARABLE"},
            ],
            "narrative_description": "Anna agrees to hand over her scarf.",
        },
        [],
    )
    assert not result.new_inventory_items and not owner.avatar.inventory
    assert "UNREGISTERED ORDINARY ITEM CANDIDATES" in result.narrative_description
    assert "did not occur" not in result.narrative_description


@pytest.mark.parametrize("item_type", ["WEAPON", "CONSUMABLE", "QUEST"])
def test_unknown_mechanical_items_still_fail_closed(item_type):
    result = prepare_intent(
        manager(),
        {
            "new_inventory_items": [
                {"id": "UNKNOWN", "name": "Powerful item", "item_type": item_type},
            ]
        },
        [],
    )
    assert not result.new_inventory_items
    assert "did not occur" in result.narrative_description


def test_inaccessible_inline_item_cannot_be_disguised_as_new_acquisition():
    npc = entity("remote", inventory=[{"id": "SCARF", "name": "Scarf"}])
    npc.current_scene_id = "OTHER"
    for identifier in ("SCARF", "INVENTED_ALIAS"):
        result = prepare_intent(
            manager(),
            {
                "new_inventory_items": [
                    {"id": identifier, "name": "Scarf", "item_type": "WEARABLE"},
                ]
            },
            [npc],
        )
        assert not result.new_inventory_items
        assert "did not occur" in result.narrative_description


@pytest.mark.asyncio
@pytest.mark.parametrize("moveable", [True, False])
async def test_local_arrival_binds_companions_before_normal_movement_guards(monkeypatch, moveable):
    action = "Мы с Анной вошли в таверну."
    async with TestSessionLocal() as db:
        owner, _ = await setup(db)
        db.add(
            WorldEntity(
                id="ANNA",
                session_id="session-1",
                entity_type="NPC",
                name="Анна",
                description="Companion",
                current_scene_id="START",
                moveable=moveable,
            )
        )
        await db.commit()
        llm = MagicMock()
        llm.aexecute_complex_task = AsyncMock(
            return_value=intent_schema(ChatProgressionIntent, owner.state)(
                new_local_place=PlaceProposal(label="Таверна", action_quote=action),
            )
        )

        async def stream(*_args, **_kwargs):
            yield MagicMock(choices=[MagicMock(delta=MagicMock(content="Вы вошли в таверну."))])

        llm.stream_simple_task = AsyncMock(return_value=stream())
        confirmation = SimpleNamespace(
            aexecute_complex_task=AsyncMock(
                return_value=decision(
                    action_quote=action,
                    companions=[{"npc_id": "ANNA", "evidence": action}],
                )
            )
        )
        monkeypatch.setattr(
            "backend.api.routes.adventures.gameplay_logic.GameMasterLLM",
            RoleLLMFactory(lambda *_a, **_k: llm),
        )
        monkeypatch.setattr(
            "backend.engine.dynamic_locations.service.GameMasterLLM",
            RoleLLMFactory(lambda *_a, **_k: confirmation),
        )
        chunks = [
            chunk
            async for chunk in GameTurnManager(db, "session-1", owner.user).process_turn(action)
        ]
        assert not any(chunk.startswith("event: error") for chunk in chunks), "".join(chunks)
        await db.refresh(owner.state)
        destination = owner.state.current_scene_id
        assert destination.startswith("dyn_")
        actual = owner.state.entity_states.get("ANNA", {}).get("current_scene_id", "START")
        assert actual == (destination if moveable else "START")
        arrival = registry(owner.state)["last_arrival"]
        assert arrival["player_entered"]
        assert arrival["companions"][0]["status"] == ("moved" if moveable else "not_moved")
        assert "present_npcs" in confirmation.aexecute_complex_task.call_args.kwargs["user_prompt"]
        check = await state_checks("session-1", db, owner.user)
        assert check["arrival"] == arrival
        with pytest.raises(HTTPException) as rejected:
            await state_checks("session-1", db, SimpleNamespace(id="other-owner"))
        assert rejected.value.status_code == 404
