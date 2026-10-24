"""Multilingual chat transitions use map IDs and grounded action evidence."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.api.routes.adventures.scene_transition_intent import confirm_scene_transition
from backend.api.routes.adventures.turn_adventure_gen import TurnAdventureGenManager
from backend.engine.llm_intents import ChatProgressionIntent
from backend.models.world_entity import WorldExit, WorldScene
from tests.conftest import TestSessionLocal
from tests.llm_fakes import RoleLLMFactory
from tests.test_game_loop import GameTurnManager, _llm_call_text, _seed_game_context


@pytest.mark.parametrize(
    "message",
    [
        "Направляясь по дороге, я захожу в город",
        "Я забежал в город",
        "Я прибыл в город на повозке",
        "Я прилетел в город",
        "Я вкатился в город",
        "Меня швырнули в город через ворота",
        "Охранники внесли меня в город",
        "Entro en la ciudad",
        "街に入ります",
        "I enter the city",
        "Ich betrete die Stadt",
    ],
)
async def test_confirm_movement_without_language_specific_keywords(message):
    classify = AsyncMock(
        return_value={
            "explicit_transition": True,
            "destination_id": "CITY",
            "action_quote": message,
        }
    )
    assert await confirm_scene_transition(
        classify,
        user_msg=message,
        target_scene_id="CITY",
        scenes=[{"id": "CITY", "label": "Город"}],
        exits=[{"to_scene_id": "CITY", "label": "Дорога в город"}],
    )


@pytest.mark.parametrize(
    "result",
    [
        None,
        {"explicit_transition": True},
        {"explicit_transition": False, "destination_id": "CITY", "action_quote": "город"},
        {"explicit_transition": True, "destination_id": "OTHER", "action_quote": "город"},
        {"explicit_transition": True, "destination_id": "CITY", "action_quote": "I enter"},
        {"explicit_transition": True, "destination_id": "CITY", "action_quote": ""},
    ],
)
async def test_missing_or_ungrounded_confirmation_fails_closed(result):
    assert not await confirm_scene_transition(
        AsyncMock(return_value=result),
        user_msg="Смотрю на город",
        target_scene_id="CITY",
        scenes=[],
        exits=[{"to_scene_id": "CITY"}],
    )


@pytest.mark.parametrize("confirmed,locked", [(True, False), (False, False), (True, True)])
async def test_chat_turn_persists_confirmed_russian_transition(monkeypatch, confirmed, locked):
    async with TestSessionLocal() as db:
        user, adv, _avatar, state = await _seed_game_context(db)
        adv.strict_rules = False
        adv.rule_enforcement_mode = "chat"
        adv.is_adventure_generator = False
        db.add_all(
            [
                WorldScene(
                    id="START", session_id="session-1", label="Дорога", description="Дорога"
                ),
                WorldScene(
                    id="CITY", session_id="session-1", label="Город", description="Городские ворота"
                ),
                WorldExit(
                    session_id="session-1",
                    from_scene_id="START",
                    to_scene_id="CITY",
                    label="Дорога в город",
                    is_locked=locked,
                ),
            ]
        )
        await db.commit()
        llm = MagicMock()
        llm.aexecute_complex_task = AsyncMock(
            return_value=ChatProgressionIntent(
                new_scene_id="CITY", narrative_description="You arrived in the city."
            )
        )

        async def stream(*_args, **_kwargs):
            yield MagicMock(choices=[MagicMock(delta=MagicMock(content="Описание локации."))])

        llm.stream_simple_task = AsyncMock(return_value=stream())
        monkeypatch.setattr(
            "backend.api.routes.adventures.gameplay_logic.GameMasterLLM",
            RoleLLMFactory(lambda *args, **kwargs: llm),
        )
        classifier = AsyncMock(
            return_value={
                "explicit_transition": confirmed,
                "destination_id": "CITY",
                "action_quote": "я захожу в город",
            }
        )
        monkeypatch.setattr(TurnAdventureGenManager, "classify_short_intent", classifier)
        chunks = [
            chunk
            async for chunk in GameTurnManager(db, "session-1", user).process_turn(
                "Направляясь по дороге, я захожу в город"
            )
        ]
        await db.refresh(state)
        expected = "CITY" if confirmed and not locked else "START"
        assert state.current_scene_id == expected
        assert llm.aexecute_complex_task.await_count >= 1
        text = _llm_call_text(llm.stream_simple_task.await_args_list[0])
        assert '"current_scene_id": "' + expected + '"' in text
        assert '"scene_changed": ' + str(confirmed and not locked).lower() in text
        assert "event: state" in "".join(chunks)
        assert classifier.await_count == (0 if locked else 1)
