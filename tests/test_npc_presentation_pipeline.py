"""Narrator footer is removed before SSE, canonical history and CHPM validation."""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import select

from backend.core.system_diagnostics import service
from backend.engine.gameplay.manager import GameTurnManager
from backend.engine.npc_presentation.settings import KEY
from backend.engine.rule_engine import GameEvent
from backend.models.chat import ChatMessage
from backend.models.world_entity import WorldEntity
from tests.conftest import TestSessionLocal
from tests.llm_fakes import RoleLLMFactory
from tests.test_game_loop import _seed_game_context


@pytest.mark.parametrize("color_rgb", [None, [140, 160, 210]])
async def test_streamed_turn_saves_metadata_but_keeps_it_out_of_story(
    setup_test_db, monkeypatch, color_rgb
):
    diagnostics = MagicMock()
    monkeypatch.setattr(service, "emit", diagnostics)
    body = "[RIN]: I can manage."
    footer = (
        "<npc-state>"
        + json.dumps(
            {
                "npcs": [
                    {
                        "npc_id": "RIN",
                        "emotion": "determination" if color_rgb is None else "vulnerability",
                        "intensity": 65,
                        "thought": "One step at a time.",
                        **({"color_rgb": color_rgb} if color_rgb is not None else {}),
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
        cue = message.to_client_dict()["portrait_state"]["npcs"]["RIN"]
        assert cue == {
            "emotion": "determination" if color_rgb is None else "vulnerability",
            "intensity": 65,
            "thought": "One step at a time.",
            **({"color_rgb": color_rgb} if color_rgb is not None else {}),
        }
        assert "PORTRAIT PRESENTATION" in llm.stream_simple_task.await_args.args[0]
        llm.stream_simple_task.assert_awaited_once()
        event = next(
            call for call in diagnostics.call_args_list if call.args == ("npc.presentation",)
        )
        assert event.kwargs["presentation_reason"] == "available"
        assert event.kwargs["selected_count"] == 1


@pytest.mark.parametrize("mode", ["off", "shadow", "live"])
@pytest.mark.parametrize("color_rgb", [None, [140, 160, 210]])
@pytest.mark.parametrize(
    "preferences,expected",
    [
        ({"emotion_palette": True}, {"emotion": "interest", "intensity": 70}),
        ({"character_thoughts": True}, {"thought": "Наконец-то можно поговорить."}),
        (
            {"emotion_palette": True, "character_thoughts": True},
            {"emotion": "interest", "intensity": 70, "thought": "Наконец-то можно поговорить."},
        ),
    ],
)
async def test_vn_presentation_uses_the_same_narrator_call_in_every_personality_mode(
    setup_test_db, monkeypatch, preferences, expected, mode, color_rgb
):
    from backend.engine.chpm import inference, rendering
    from backend.engine.chpm.runtime import current
    from backend.engine.chpm.schema import KernelState, Settings
    from backend.engine.chpm.state import KEY as CHPM_KEY
    from tests.test_chpm_turn import ChpmRoles
    from tests.test_vn_turn_integration import final_payload, install_roles, seed_vn

    body = 'Лина: "Спасибо. Теперь можно поговорить."'
    footer = (
        "<npc-state>"
        + json.dumps(
            {
                "npcs": [
                    {
                        "npc_id": "LINA",
                        "emotion": "interest" if color_rgb is None else "vulnerability",
                        "intensity": 70,
                        "thought": "Наконец-то можно поговорить.",
                        **({"color_rgb": color_rgb} if color_rgb is not None else {}),
                    }
                ]
            },
            ensure_ascii=False,
        )
        + "</npc-state>"
    )

    class PresentationRoles(ChpmRoles):
        async def stream(self, *args, **kwargs):
            self.prompts.append((args, kwargs))

            async def chunks():
                for part in (body, footer[:7], footer[7:-5], footer[-5:]):
                    yield MagicMock(
                        choices=[MagicMock(delta=MagicMock(content=part), finish_reason="stop")]
                    )

            return chunks()

    roles = PresentationRoles()
    install_roles(monkeypatch, roles)
    monkeypatch.setattr(inference, "GameMasterLLM", roles)
    monkeypatch.setattr(rendering, "GameMasterLLM", roles)
    async with TestSessionLocal() as db:
        user, _, state, _ = await seed_vn(db)
        state.entity_states = {
            **state.entity_states,
            KEY: preferences,
            CHPM_KEY: KernelState(
                settings=Settings(mode=mode, actor_ids=["LINA"], failure_policy="strict")
            ).model_dump(),
        }
        await db.commit()
        manager = GameTurnManager(db, "session-1", user)
        events = [event async for event in manager.process_turn("Давай поговорим.")]
        final = final_payload(events)
        assert final["status"] == "success", "".join(events)
        assert current(manager) is None  # Completed turns release their turn-local analysis.
        assert (
            roles.chpm_calls
            == {
                "off": [],
                "shadow": ["perception", "proposal"],
                "live": ["perception", "proposal", "validation"],
            }[mode]
        )
        assert final["sheet"]["portrait_preferences"] == {
            "emotion_palette": False,
            "character_thoughts": False,
            "brightness": 40,
            **preferences,
        }
        message = await db.scalar(
            select(ChatMessage).where(
                ChatMessage.session_id == "session-1",
                ChatMessage.role == "assistant",
                ChatMessage.content == body,
            )
        )
        assert message is not None
        accepted = dict(expected)
        if color_rgb is not None and preferences.get("emotion_palette"):
            accepted.update(emotion="vulnerability", color_rgb=color_rgb)
        assert message.to_client_dict()["portrait_state"]["npcs"]["LINA"] == accepted
        assert "<npc-state>" not in "".join(events)
        assert len(roles.prompts) == 1
        prompt = roles.prompts[0][0][0]
        assert "enabled for this reply" in prompt
        assert "without NPC Personality" in prompt
        assert "JSON keys" in prompt and "English" in prompt
        narrator_context = json.dumps(roles.prompts[0], ensure_ascii=False)
        assert "Values honesty." in narrator_context
        assert ("CHPM DIALOGUE CONTRACT" in narrator_context) is (mode == "live")
        last_input = roles.prompts[0][1]["messages"][-1]["content"]
        assert "PORTRAIT OUTPUT" in last_input
        assert "private metadata keys and enum identifiers" in last_input
        assert "RUSSIAN" in last_input
