"""Completed narration reaches canonical locations in the same turn, without more inference."""

import json
from unittest.mock import MagicMock

import pytest
from sqlalchemy import select

from backend.api.routes.adventures.gameplay_logic import GameTurnManager
from backend.engine.gameplay.world import AdventureLogic
from backend.engine.narrated_items.schema import ItemExtraction
from backend.engine.scene_illustrations.snapshots import REGISTRY_KEY
from backend.models.chat import ChatMessage
from backend.models.session_state import SessionState
from backend.models.world_entity import WorldEntity, WorldExit, WorldScene
from tests.conftest import TestSessionLocal
from tests.test_vn_turn_integration import TurnRoles, final_payload, install_roles, seed_vn

NPC_EXIT = "Лина вышла из таверны в лабораторию и закрыла за собой дверь."
GROUP_ENTRY = "Мы с Линой вошли в исследовательскую лабораторию. Дверь закрылась за нашими спинами."
GROUP_ACTION = "Я вслед за Линой вошёл в исследовательскую лабораторию."


class MovementRoles(TurnRoles):
    def __init__(self, *, group):
        super().__init__()
        self.group = group
        self.text = GROUP_ENTRY if group else NPC_EXIT

    async def structured(self, *args, **kwargs):
        schema = kwargs.get("response_model") or args[2]
        if not issubclass(schema, ItemExtraction):
            return await super().structured(*args, **kwargs)
        self.calls.append((schema.__name__, args, kwargs))
        packet = {
            "actions": [],
            "condition_updates": [],
            "scene_updates": [],
            "final_frame_actions": [],
            "movements": [
                {
                    "actor_id": actor,
                    "destination_scene_id": "LAB",
                    "presence": "present",
                    "basis": "completed",
                    "evidence": self.text,
                    "player_evidence": GROUP_ACTION if actor == "__player__" else None,
                }
                for actor in (["__player__", "LINA"] if self.group else ["LINA"])
            ],
        }
        return packet

    async def stream(self, *args, **kwargs):
        self.prompts.append((args, kwargs))

        async def chunks():
            yield MagicMock(choices=[MagicMock(delta=MagicMock(content=self.text))])

        return chunks()


@pytest.mark.asyncio
@pytest.mark.parametrize("group", [False, True])
async def test_completed_departure_updates_locations_cast_and_saved_moment(monkeypatch, group):
    roles = MovementRoles(group=group)
    install_roles(monkeypatch, roles)
    async with TestSessionLocal() as db:
        user, _, state, _ = await seed_vn(db)
        lina = await db.scalar(select(WorldEntity).where(WorldEntity.id == "LINA"))
        lina.moveable = True
        db.add(
            WorldScene(
                id="LAB",
                session_id=state.session_id,
                label="Исследовательская лаборатория",
                description="A bright laboratory.",
            )
        )
        db.add(
            WorldExit(
                session_id=state.session_id,
                from_scene_id="START",
                to_scene_id="LAB",
                label="Lab door",
                exit_type="bidirectional",
                is_locked=False,
            )
        )
        await db.commit()
        manager = GameTurnManager(db, state.session_id, user)

        chunks = [
            chunk
            async for chunk in manager.process_turn(
                GROUP_ACTION if group else "Я остаюсь здесь, пока Лина выходит."
            )
        ]

        assert not any(chunk.startswith("event: error") for chunk in chunks), "".join(chunks)
        payload = final_payload(chunks)
        await db.refresh(state)
        assert state.current_scene_id == ("LAB" if group else "START")
        assert payload["scene_id"] == state.current_scene_id
        assert state.in_game_time == (5 if group else 0)
        assert state.entity_states["LINA"]["current_scene_id"] == "LAB"
        entities = await AdventureLogic.build_session_entities(db, state)
        assert ("LINA" in {row["id"] for row in entities}) is group
        reply = await db.scalar(
            select(ChatMessage).where(
                ChatMessage.content == roles.text, ChatMessage.role == "assistant"
            )
        )
        moment = state.entity_states[REGISTRY_KEY]["snapshots"][reply.id]
        assert reply.scene_id == state.current_scene_id
        assert reply.npc_journal["game_minute"] == state.in_game_time
        assert moment["scene_id"] == state.current_scene_id
        assert (
            "Лина" in json.dumps(moment["visible_facts"]["characters"], ensure_ascii=False)
        ) is group
        assert "SECRET_GOAL_NOT_PUBLIC" not in json.dumps(payload)
        assert len(roles.calls) == 3
        saved_id = state.id
    async with TestSessionLocal() as db:
        saved = await db.get(SessionState, saved_id)
        assert saved.current_scene_id == ("LAB" if group else "START")
        assert saved.entity_states["LINA"]["current_scene_id"] == "LAB"


class ArrivalFacts(MovementRoles):
    def __init__(self, authored):
        super().__init__(group=True)
        self.authored = authored
        self.text += " The laboratory has blue tiles."

    async def structured(self, *args, **kwargs):
        schema = kwargs.get("response_model") or args[2]
        result = await super().structured(*args, **kwargs)
        if schema.__name__.startswith("VNProgressionIntent"):
            return result.model_copy(update={"extra_time_minutes": 3})
        if isinstance(result, dict):
            result["scene_updates"] = [
                {
                    "operation": "record",
                    "key": "floor",
                    "kind": "environment",
                    "subject_id": "LAB",
                    "detail": "Blue laboratory tiles.",
                    "evidence": "Quiet common room."
                    if self.authored
                    else "The laboratory has blue tiles.",
                }
            ]
        return result


@pytest.mark.asyncio
@pytest.mark.parametrize("authored", [False, True])
async def test_arrival_facts_belong_to_destination_and_prior_room_sources_cannot_move_with_player(
    monkeypatch, authored
):
    from backend.engine.scene_continuity.ledger import read

    roles = ArrivalFacts(authored)
    install_roles(monkeypatch, roles)
    async with TestSessionLocal() as db:
        user, _, state, _ = await seed_vn(db)
        lina = await db.scalar(select(WorldEntity).where(WorldEntity.id == "LINA"))
        lina.moveable = True
        db.add(
            WorldScene(
                id="LAB",
                session_id=state.session_id,
                label="Laboratory",
                description="A bright laboratory.",
            )
        )
        db.add(
            WorldExit(
                session_id=state.session_id,
                from_scene_id="START",
                to_scene_id="LAB",
                label="Door",
                is_locked=False,
            )
        )
        await db.commit()
        events = [
            event
            async for event in GameTurnManager(db, state.session_id, user).process_turn(
                GROUP_ACTION
            )
        ]
        assert final_payload(events)["scene_id"] == "LAB"
        await db.refresh(state)
        assert state.in_game_time == 3  # Resolved time must not be charged twice at arrival.
        ledger = read(state.entity_states)
        if authored:
            assert not ledger.records and ledger.last_check["rejected"]
        else:
            assert {row.scene_id for row in ledger.records.values()} == {"LAB"}
            assert {row.subject_id for row in ledger.records.values()} == {"LAB"}
            assert not ledger.last_check["rejected"]
        assert len(roles.calls) == 3
