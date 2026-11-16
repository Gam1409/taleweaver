"""Debug provenance survives persistence and copying without changing story contents."""

import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, select, text

from backend.api.routes.adventures.gameplay_logic import GameTurnManager
from backend.engine.debug_transcript import debug_message_scope
from backend.engine.npc_journal.messages import copy_messages
from backend.models.chat import ChatMessage
from backend.models.game_session import GameSession
from tests.conftest import TestSessionLocal
from tests.test_game_loop import _seed_game_context


def test_additive_debug_migration_preserves_legacy_text_and_downgrades():
    path = (
        Path(__file__).resolve().parents[1]
        / "alembic/versions/d9b3e5a7c904_persist_chat_debug_flag.py"
    )
    spec = importlib.util.spec_from_file_location("debug_flag_migration", path)
    assert spec and spec.loader
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine("sqlite://")
    try:
        with engine.begin() as connection:
            connection.execute(
                text("CREATE TABLE chat_messages (id TEXT PRIMARY KEY, content TEXT)")
            )
            connection.execute(
                text("INSERT INTO chat_messages VALUES ('old', 'Exact old story text.')")
            )
            with Operations.context(MigrationContext.configure(connection)):
                migration.upgrade()
                assert connection.execute(
                    text("SELECT content, is_debug FROM chat_messages")
                ).one() == ("Exact old story text.", 0)
                migration.downgrade()
                assert "is_debug" not in {
                    column["name"] for column in inspect(connection).get_columns("chat_messages")
                }
                assert (
                    connection.execute(text("SELECT content FROM chat_messages")).scalar()
                    == "Exact old story text."
                )
    finally:
        engine.dispose()


def test_debug_message_scope_restores_nested_and_failed_commands():
    manager = SimpleNamespace()
    with debug_message_scope(manager):
        assert manager._debug_message_scope is True
        with debug_message_scope(manager):
            assert manager._debug_message_scope is True
        assert manager._debug_message_scope is True
    assert manager._debug_message_scope is False
    with pytest.raises(RuntimeError), debug_message_scope(manager):
        raise RuntimeError("Interrupted command")
    assert manager._debug_message_scope is False


@pytest.mark.asyncio
async def test_unprefixed_debug_output_remains_debug_after_reload_and_session_copy():
    async with TestSessionLocal() as db:
        user, adventure, avatar, state = await _seed_game_context(db)
        manager = GameTurnManager(db, state.session_id, user)
        manager.state, manager.avatar, manager.adventure = state, avatar, adventure
        manager._unhide_entities_in_text = AsyncMock()
        with debug_message_scope(manager):
            diagnostic = await manager._save_chat_message(
                "assistant", "Generated technical output without a prefix."
            )
        story = await manager._save_chat_message("assistant", "An ordinary reply.")
        db.add(
            GameSession(
                id="copied",
                user_id=user.id,
                template_id=adventure.id,
                avatar_id=avatar.id,
                status="active",
            )
        )
        await db.commit()
        mapping = await copy_messages(db, state.session_id, "copied")
        await db.commit()
        await db.refresh(diagnostic)
        assert diagnostic.is_debug and not story.is_debug
        copied = await db.scalar(
            select(ChatMessage).where(ChatMessage.id == mapping[diagnostic.id])
        )
        assert copied.is_debug and copied.content == diagnostic.content
        assert copied.to_client_dict()["is_debug"] is True


@pytest.mark.asyncio
async def test_debug_analysis_cannot_hold_a_story_learning_lease_or_be_claimed():
    import time

    from backend.engine.npc_journal import queue

    async with TestSessionLocal() as db:
        _, _, _, state = await _seed_game_context(db)
        technical = ChatMessage(
            session_id=state.session_id,
            role="assistant",
            content="Technical output.",
            is_debug=True,
            npc_journal={"status": "running", "attempts": 1, "lease_until": time.time() + 60},
        )
        story = ChatMessage(
            session_id=state.session_id,
            role="assistant",
            content="Lina introduces herself.",
            npc_journal={"status": "pending", "attempts": 0},
        )
        db.add_all([technical, story])
        await db.commit()
        assert await queue.next_message(db, state.session_id) == story.id
        technical.npc_journal = {"status": "pending", "attempts": 0}
        await db.commit()
        assert await queue.claim(db, technical) is None
        assert (await queue.claim(db, story))["status"] == "running"


@pytest.mark.asyncio
async def test_debug_analysis_is_absent_from_retry_timers_and_character_learning_status(
    monkeypatch,
):
    import time

    from backend.api.routes.adventures import session_npcs
    from backend.engine.npc_journal import queue

    monkeypatch.setattr(session_npcs, "schedule", lambda *args, **kwargs: None)
    async with TestSessionLocal() as db:
        user, _, _, state = await _seed_game_context(db)
        technical = ChatMessage(
            session_id=state.session_id,
            role="assistant",
            content="Technical failure.",
            is_debug=True,
            npc_journal={"status": "failed", "attempts": 1, "retry_after": time.time() + 60},
        )
        db.add(technical)
        await db.commit()
        assert await queue.next_retry_at(db, state.session_id) is None
        status = await session_npcs.list_characters(state.session_id, db, user)
        assert status["pending"] == status["failed"] == 0
        assert await session_npcs.retry_learning(state.session_id, db, user) == {"queued": 0}
        await db.refresh(technical)
        assert technical.npc_journal["status"] == "failed"
