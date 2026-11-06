"""Narrator footer is removed before SSE, canonical history and CHPM validation."""

import json
from unittest.mock import AsyncMock, MagicMock

from sqlalchemy import select

from backend.engine.gameplay.manager import GameTurnManager
from backend.engine.npc_presentation.settings import KEY
from backend.engine.rule_engine import GameEvent
from backend.models.chat import ChatMessage
from backend.models.world_entity import WorldEntity
from tests.conftest import TestSessionLocal
from tests.llm_fakes import RoleLLMFactory
from tests.test_game_loop import _seed_game_context


async def test_streamed_turn_saves_metadata_but_keeps_it_out_of_story(setup_test_db, monkeypatch):
    body = "[RIN]: I can manage."
    footer = (
        "<npc-state>"
        + json.dumps(
            {
                "npcs": [
                    {
                        "npc_id": "RIN",
                        "emotion": "determination",
                        "intensity": 65,
                        "thought": "One step at a time.",
                    }
                ]
            }
        )
        + "</npc-state>"
    )
    async with TestSessionLocal() as db:
        user, _, _, state = await _seed_game_context(db)
        state.entity_states = {KEY: {"emotion_palette": True, "character_thoughts": True}}
        db.add(
            WorldEntity(
                id="RIN",
                session_id="session-1",
                template_id="adv-1",
                name="Rin",
                description="A determined physician.",
                entity_type="NPC",
                current_scene_id="START",
            )
        )
        await db.commit()
        llm = MagicMock()
        llm.aexecute_complex_task = AsyncMock(
            return_value=GameEvent(narrative_description="Rin replies.")
        )

        async def chunks():
            for char in body + footer:
                yield MagicMock(choices=[MagicMock(delta=MagicMock(content=char))])

        llm.stream_simple_task = AsyncMock(return_value=chunks())
        monkeypatch.setattr(
            "backend.api.routes.adventures.gameplay_logic.GameMasterLLM",
            RoleLLMFactory(lambda *_args, **_kwargs: llm),
        )
        events = [
            event
            async for event in GameTurnManager(db, "session-1", user).process_turn(
                "Can you do this?"
            )
        ]
        visible = "".join(
            json.loads(event.split("data: ", 1)[1])["content"]
            for event in events
            if event.startswith("event: chunk")
        )
        assert visible == body
        assert "<npc-state>" not in "".join(events)
        message = await db.scalar(
            select(ChatMessage).where(
                ChatMessage.session_id == "session-1", ChatMessage.role == "assistant"
            )
        )
        assert message.content == body
        assert message.to_client_dict()["portrait_state"]["npcs"]["RIN"]["intensity"] == 65
        assert "OPTIONAL PORTRAIT PRESENTATION" in llm.stream_simple_task.await_args.args[0]
        llm.stream_simple_task.assert_awaited_once()
