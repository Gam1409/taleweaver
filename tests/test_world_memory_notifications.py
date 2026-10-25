"""System notices follow the session language while stored memory stays canonical."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from backend.api.routes.adventures.gameplay_logic import GameTurnManager
from backend.core.content_language import LANGUAGES
from backend.engine.rule_engine import GameEvent, WorldMemoryUpdate
from backend.engine.world_memory_notifications import (
    memory_saved_message,
    notification_language,
)
from backend.models.chat import ChatMessage
from backend.models.game_session import GameSession
from tests.conftest import TestSessionLocal
from tests.test_game_loop import _seed_game_context

FACT = "Лина вернула книгу — BOOK_01."


@pytest.mark.parametrize(
    "language,prefix",
    [
        ("en", "Memory saved"),
        ("de", "Erinnerung gespeichert"),
        ("fr", "Souvenir enregistré"),
        ("es", "Recuerdo guardado"),
        ("it", "Ricordo salvato"),
        ("pt-BR", "Memória salva"),
        ("ru-RU", "Воспоминание сохранено"),
        ("ja", "記憶を保存しました"),
        ("zh", "记忆已保存"),
    ],
)
def test_supported_languages_preserve_fact_and_identifier(language, prefix):
    notice = memory_saved_message(FACT, "local", "positive", language)
    assert notice.startswith(prefix + " (")
    assert notice.endswith(": " + FACT)


def test_all_selectable_languages_have_notification_labels():
    for language in LANGUAGES.values():
        assert memory_saved_message(FACT, "global", "neutral", language).endswith(FACT)


def test_russian_scope_and_emotion_labels():
    assert memory_saved_message(FACT, "local", "negative", "Russian") == (
        "Воспоминание сохранено (текущая сцена, отрицательное): " + FACT
    )
    assert memory_saved_message(FACT, "global", "neutral", "Russian") == (
        "Воспоминание сохранено (весь мир, нейтральное): " + FACT
    )


@pytest.mark.parametrize("language", ["unsupported", "", None])
def test_invalid_legacy_language_falls_back_to_english(language):
    assert memory_saved_message(FACT, "global", "positive", language) == (
        "Memory saved (global, positive): " + FACT
    )


@pytest.mark.asyncio
async def test_explicit_turn_language_does_not_query_database():
    manager = SimpleNamespace(turn_language="ja", db=AsyncMock())
    assert await notification_language(manager) == "Japanese"
    manager.db.scalar.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "saved,override,expected",
    [
        ("Russian", None, "Воспоминание сохранено (текущая сцена, положительное): "),
        ("Japanese", None, "記憶を保存しました (現在のシーン, 肯定的): "),
        ("English", None, "Memory saved (scene-local, positive): "),
        ("English", "Russian", "Воспоминание сохранено (текущая сцена, положительное): "),
        (None, None, "Recuerdo guardado (escena actual, positivo): "),
    ],
)
async def test_persisted_notice_language_and_memory_json(setup_test_db, saved, override, expected):
    async with TestSessionLocal() as db:
        user, adventure, avatar, state = await _seed_game_context(db)
        session = await db.get(GameSession, state.session_id)
        session.content_language = saved
        user.default_language = "Spanish"
        adventure.language = "German"
        await db.commit()
        db.expire(state, ["session"])
        manager = GameTurnManager(
            db, state.session_id, user, state=state, adventure=adventure, avatar=avatar
        )
        manager.turn_language = override

        def event():
            return GameEvent(
                new_world_memories=[
                    WorldMemoryUpdate(description=FACT, scope="local", emotion="positive")
                ]
            )

        messages = await manager._apply_game_event(event())
        assert expected + FACT in messages
        await db.commit()
        await db.refresh(state)
        memory = state.world_memories[0]
        assert memory["scope"] == "local"
        assert memory["emotion"] == "positive"
        assert memory["scene_id"] == "START"
        assert memory["description"] == FACT

        # Retrying the same fact must not append another memory or notification.
        await manager._apply_game_event(event())
        await db.commit()
        notices = list(
            await db.scalars(
                select(ChatMessage.content).where(
                    ChatMessage.session_id == state.session_id, ChatMessage.role == "system"
                )
            )
        )
        assert notices.count(expected + FACT) == 1
        assert len(state.world_memories) == 1
