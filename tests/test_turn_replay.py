"""Full retries restore canonical state rather than executing the action twice."""

import pytest
from sqlalchemy import select

from backend.api.routes.adventures.gameplay_logic import GameTurnManager
from backend.engine.turn_replay import service
from backend.models.chat import ChatMessage
from backend.models.session_state import SessionState
from backend.models.turn_replay import TurnReplay
from backend.models.world_entity import WorldEntity, WorldScene
from tests.conftest import TestSessionLocal
from tests.test_game_loop import _seed_game_context

pytestmark = pytest.mark.asyncio


async def seed(db):
    user, adventure, avatar, state = await _seed_game_context(db)
    adventure.rule_enforcement_mode = "vn"
    db.add(WorldScene(id="START", session_id=state.session_id, label="Room", description="Room"))
    db.add(
        WorldEntity(
            id="NPC",
            session_id=state.session_id,
            entity_type="NPC",
            name="Мира",
            description="Nurse",
            current_scene_id="START",
            inventory=[],
        )
    )
    await db.commit()
    return user, avatar, state


async def fake_cycle(manager, message, auto_visualize=False, language=None):
    manager.avatar.hp -= 10
    manager.state.in_game_time += 5
    manager.state.entity_states = {
        **(manager.state.entity_states or {}),
        "NPC": {"presence": "absent"},
    }
    manager.avatar.inventory = [{"id": "KEY", "name": "Key"}]
    manager.db.add(
        WorldEntity(
            id="NEW",
            session_id=manager.game_id,
            entity_type="OBJECT",
            name="Found",
            description="Item",
            current_scene_id="START",
        )
    )
    await manager._save_chat_message("assistant", f"Response to {message}")
    await manager.db.commit()
    yield 'event: final\ndata: {"status":"success"}\n\n'


async def messages(db):
    return list(
        await db.scalars(
            select(ChatMessage)
            .where(ChatMessage.session_id == "session-1")
            .order_by(ChatMessage.created_at, ChatMessage.id)
        )
    )


async def complete(db, user):
    manager = GameTurnManager(db, "session-1", user)
    chunks = [chunk async for chunk in manager.process_turn("Я открываю дверь.")]
    assert any(chunk.startswith("event: final") for chunk in chunks)
    return (await messages(db))[-1].id


async def test_full_retry_does_not_double_apply_time_damage_or_items(setup_test_db, monkeypatch):
    monkeypatch.setattr(GameTurnManager, "_run_llm_cycle", fake_cycle)
    async with TestSessionLocal() as db:
        user, _, _ = await seed(db)
        original_id = await complete(db, user)
        manager = GameTurnManager(db, "session-1", user)
        chunks = [
            chunk async for chunk in manager.process_turn("IGNORED", replay_message_id=original_id)
        ]
        assert any(chunk.startswith("event: final") for chunk in chunks), chunks
        assert manager.avatar.hp == 90
        assert manager.state.in_game_time == 5
        assert len(manager.avatar.inventory) == 1
        history = await messages(db)
        assert [m.role for m in history] == ["user", "assistant"]
        assert history[0].content == "Я открываю дверь."
        assert history[-1].id != original_id
        assert await db.get(ChatMessage, original_id) is None
        snapshot = await db.get(TurnReplay, "session-1")
        assert snapshot.status == "ready" and snapshot.backup is None
        # Repeatability: a third attempt still starts from the same original snapshot.
        third = GameTurnManager(db, "session-1", user)
        _ = [
            chunk async for chunk in third.process_turn("ignored", replay_message_id=history[-1].id)
        ]
        assert third.avatar.hp == 90 and third.state.in_game_time == 5


@pytest.mark.parametrize("incomplete", [False, True])
async def test_failed_retry_restores_original_committed_result(
    setup_test_db, monkeypatch, incomplete
):
    monkeypatch.setattr(GameTurnManager, "_run_llm_cycle", fake_cycle)
    async with TestSessionLocal() as db:
        user, _, _ = await seed(db)
        original_id = await complete(db, user)

        async def failed(manager, *args, **kwargs):
            manager.state.in_game_time = 999
            manager.avatar.hp = 1
            await manager.db.commit()
            if incomplete:
                yield 'event: final\ndata: {"narration_incomplete":true}\n\n'
            else:
                yield 'event: error\ndata: {"detail":"Model unavailable"}\n\n'

        monkeypatch.setattr(GameTurnManager, "_run_llm_cycle", failed)
        manager = GameTurnManager(db, "session-1", user)
        chunks = [
            chunk async for chunk in manager.process_turn("ignored", replay_message_id=original_id)
        ]
        assert any(chunk.startswith("event: error") for chunk in chunks)
        state = await db.scalar(select(SessionState).where(SessionState.session_id == "session-1"))
        assert state.in_game_time == 5
        assert (await messages(db))[-1].id == original_id
        assert (await db.get(TurnReplay, "session-1")).status == "ready"


async def test_disconnect_recovers_immediately(setup_test_db, monkeypatch):
    monkeypatch.setattr(GameTurnManager, "_run_llm_cycle", fake_cycle)
    async with TestSessionLocal() as db:
        user, _, _ = await seed(db)
        original_id = await complete(db, user)
        manager = GameTurnManager(db, "session-1", user)
        stream = manager.process_turn("ignored", replay_message_id=original_id)
        first = await anext(stream)
        assert first.startswith("event: replay_history")
        await stream.aclose()
        assert (await messages(db))[-1].id == original_id
        assert (await db.get(TurnReplay, "session-1")).status == "ready"


async def test_startup_recovers_durable_backup(setup_test_db, monkeypatch):
    monkeypatch.setattr(GameTurnManager, "_run_llm_cycle", fake_cycle)
    async with TestSessionLocal() as db:
        user, _, _ = await seed(db)
        original_id = await complete(db, user)
        manager = GameTurnManager(db, "session-1", user)
        await service.begin(manager, original_id)
    async with TestSessionLocal() as db:
        await service.recover_interrupted(db)
        assert (await messages(db))[-1].id == original_id
        state = await db.scalar(select(SessionState).where(SessionState.session_id == "session-1"))
        assert state.in_game_time == 5


async def test_stale_or_legacy_response_does_not_rewind(setup_test_db, monkeypatch):
    monkeypatch.setattr(GameTurnManager, "_run_llm_cycle", fake_cycle)
    async with TestSessionLocal() as db:
        user, _, _ = await seed(db)
        original_id = await complete(db, user)
        manager = GameTurnManager(db, "session-1", user)
        chunks = [chunk async for chunk in manager.process_turn("ignored", replay_message_id="old")]
        assert any(chunk.startswith("event: error") for chunk in chunks)
        assert (await messages(db))[-1].id == original_id


async def test_rewind_restores_memories_and_only_this_sessions_awards(setup_test_db, monkeypatch):
    from backend.engine.turn_replay.snapshot import capture, restore
    from backend.models.memory_rag import MemoryIndexState, MemorySummary

    async with TestSessionLocal() as db:
        user, _, _ = await seed(db)
        user_id = user.id
        user.earned_awards = [{"session_id": "session-1", "title": "Before"}]
        db.add(MemoryIndexState(session_id="session-1", user_id=user_id, epoch=2))
        await db.commit()
        before = await capture(db, "session-1")
        user.earned_awards = [
            {"session_id": "session-1", "title": "After"},
            {"session_id": "another-session", "title": "Keep"},
        ]
        db.add(
            MemorySummary(
                session_id="session-1",
                user_id=user_id,
                layer="episode",
                text="Discarded outcome",
                source_hash="hash",
                source_message_ids=[],
            )
        )
        await db.commit()
        await restore(db, "session-1", before)
        await db.commit()
        await db.refresh(user)
        assert user.earned_awards == [
            {"session_id": "another-session", "title": "Keep"},
            {"session_id": "session-1", "title": "Before"},
        ]
        assert await db.scalar(select(MemorySummary.id)) is None
        assert (await db.get(MemoryIndexState, "session-1")).epoch == 3
