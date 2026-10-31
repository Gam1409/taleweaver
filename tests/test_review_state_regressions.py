"""Cross-transaction recovery and authoritative state regression tests."""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.api.routes.adventures.gameplay_logic import GameTurnManager
from backend.api.routes.adventures.turn_containers import ContainerInteractions
from backend.engine.memory_rag import recall_sources
from backend.engine.memory_rag.documents import collect_documents
from backend.engine.npc_journal.queue import eligible
from backend.engine.session_portraits import _reserve_portrait, _try_save_portrait
from backend.engine.turn_replay import service
from backend.engine.turn_replay.transactions import release_for_model
from backend.models.adventure_template import AdventureTemplate
from backend.models.avatar import Avatar
from backend.models.base import Base
from backend.models.chat import ChatMessage
from backend.models.session_state import SessionState
from backend.models.world_entity import WorldEntity
from tests.conftest import TestSessionLocal
from tests.test_living_world import seed


@pytest.mark.parametrize(
    "base,override,hidden,carried,available",
    [
        ("START", "ROOM", False, False, False),
        ("ROOM", "START", False, False, True),
        ("START", "START", True, False, False),
        ("START", "START", False, True, False),
    ],
)
async def test_container_uses_effective_access(base, override, hidden, carried, available):
    async with TestSessionLocal() as db:
        _, state = await seed(db)
        chest = WorldEntity(
            session_id=state.session_id,
            id="CHEST",
            name="Chest",
            description="A wooden box",
            entity_type="OBJECT",
            item_type="CONTAINER",
            current_scene_id=base,
            inventory=[],
        )
        db.add(chest)
        state.entity_states = {
            "CHEST": {"current_scene_id": override, "is_hidden": hidden, "is_in_inventory": carried}
        }
        await db.commit()
        manager = SimpleNamespace(
            db=db, game_id=state.session_id, state=state, avatar=SimpleNamespace(inventory=[])
        )
        found, _, _ = await ContainerInteractions._resolve_container_target(manager, "chest")
        assert (found is not None) == available


async def test_portrait_request_cannot_overwrite_a_restored_timeline():
    async with TestSessionLocal() as db:
        user, state = await seed(db)
        state.entity_states = {"LILI": {"image_url": "/data/restored.png"}}
        await db.commit()
        original = deepcopy(state.entity_states)
        token = await _reserve_portrait(db, state, "LILI")
        state.entity_states = original
        await db.commit()
        with pytest.raises(HTTPException) as failure:
            await _try_save_portrait(state.session_id, "LILI", user.id, "/data/obsolete.png", token)
        assert failure.value.status_code == 409
        await db.refresh(state)
        assert state.entity_states["LILI"]["image_url"] == "/data/restored.png"


async def test_incomplete_narration_is_visible_but_not_canonical_memory():
    async with TestSessionLocal() as db:
        user, state = await seed(db)
        task = {"status": "incomplete", "attempts": 0}
        partial = ChatMessage(
            session_id=state.session_id,
            role="assistant",
            content="Unfinished promise",
            npc_journal=task,
        )
        db.add(partial)
        await db.commit()
        assert partial.content == "Unfinished promise"
        assert not eligible(task, 1000)
        documents = await collect_documents(db, state, user.id)
        assert all(partial.id not in doc.source_message_ids for doc in documents)
        bounded = await recall_sources.collect_documents(db, state, user.id, query="promise")
        assert all(partial.id not in doc.source_message_ids for doc in bounded)


async def test_foreground_recall_load_is_bounded_and_old_vector_hits_are_validated():
    async with TestSessionLocal() as db:
        user, state = await seed(db)
        old = ChatMessage(
            id="old-evidence",
            session_id=state.session_id,
            role="assistant",
            content="A copper key was found.",
        )
        db.add(old)
        await db.flush()
        for i in range(500):
            db.add(
                ChatMessage(
                    session_id=state.session_id,
                    role="assistant",
                    content=f"Ordinary conversation {i}.",
                )
            )
        await db.commit()
        documents = await recall_sources.collect_documents(
            db, state, user.id, candidates=[{"source_message_ids": [old.id]}]
        )
        ids = {mid for doc in documents for mid in doc.source_message_ids}
        assert old.id in ids
        assert len(ids) <= recall_sources.MAX_SOURCE_MESSAGES
        await db.delete(old)
        await db.commit()
        documents = await recall_sources.collect_documents(
            db, state, user.id, candidates=[{"source_message_ids": ["old-evidence"]}]
        )
        assert not any("old-evidence" in doc.source_message_ids for doc in documents)


async def test_model_boundary_releases_writer_and_recovery_preserves_input(tmp_path):
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path}/turn.db", connect_args={"timeout": 0.1}
    )
    try:
        async with engine.begin() as conn:
            await conn.execute(text("PRAGMA journal_mode=WAL"))
            await conn.run_sync(Base.metadata.create_all)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        async with sessions() as first:
            user, state = await seed(first)
            avatar = await first.get(Avatar, state.avatar_id)
            adventure = await first.get(AdventureTemplate, state.template_id)
            manager = SimpleNamespace(
                db=first,
                game_id=state.session_id,
                user=user,
                state=state,
                avatar=avatar,
                adventure=adventure,
                _unhide_entities_in_text=AsyncMock(),
            )
            await service.record_before(manager, "I enter the room.")
            message = await GameTurnManager._save_chat_message(manager, "user", "I enter the room.")
            message_id = message.id
            await release_for_model(manager)
            async with sessions() as second:
                await second.execute(
                    text("UPDATE game_sessions SET status='active' WHERE id='session-1'")
                )
                await second.commit()
            original_time = state.in_game_time
            state.in_game_time += 60
            await release_for_model(manager)
            # Simulate a process restart/failure after mechanics were checkpointed.
            assert await service.recover(first, "session-1")
            restored = await first.scalar(
                select(SessionState).where(SessionState.session_id == "session-1")
            )
            assert restored.in_game_time == original_time
            saved = await first.get(ChatMessage, message_id)
            assert saved.content == "I enter the room."
    finally:
        await engine.dispose()


async def test_failed_input_retry_does_not_duplicate_the_message():
    async with TestSessionLocal() as db:
        user, state = await seed(db)
        manager = SimpleNamespace(
            db=db,
            game_id=state.session_id,
            state=state,
            user=user,
            avatar=await db.get(Avatar, state.avatar_id),
            adventure=await db.get(AdventureTemplate, state.template_id),
        )
        manager._save_chat_message = AsyncMock(side_effect=lambda role, text: None)
        await service.record_before(manager, "Try the door.")
        message = ChatMessage(session_id=state.session_id, role="user", content="Try the door.")
        db.add(message)
        await db.commit()
        retried = await service.record_input(manager, "Try the door.")
        assert retried.id == message.id
        manager._save_chat_message.assert_not_awaited()


def test_chronicle_does_not_summarize_partial_narration():
    from backend.engine.memory_rag.chronicle import _bounded

    rows = [
        SimpleNamespace(
            id=str(i), role="assistant", content=f"Confirmed event {i}.", npc_journal=None
        )
        for i in range(10)
    ]
    rows.insert(
        3,
        SimpleNamespace(
            id="partial",
            role="assistant",
            content="UNFINISHED_EVIDENCE",
            npc_journal={"status": "incomplete"},
        ),
    )
    batch = _bounded(rows, {})
    assert batch and "UNFINISHED_EVIDENCE" not in batch["events"]


async def test_failed_normal_turn_restores_state_and_retries_one_input(monkeypatch):
    from tests.test_turn_replay import seed as seed_turn

    async def failed_cycle(manager, *args, **kwargs):
        await release_for_model(manager)
        manager.avatar.hp -= 10
        manager.state.in_game_time += 60
        await release_for_model(manager)
        yield 'event: error\ndata: {"detail":"Provider failed","retryable":true}\n\n'

    monkeypatch.setattr(GameTurnManager, "_run_llm_cycle", failed_cycle)
    async with TestSessionLocal() as db:
        user, avatar, state = await seed_turn(db)
        hp, world_time = avatar.hp, state.in_game_time
        for _ in range(2):
            manager = GameTurnManager(db, "session-1", user)
            chunks = [chunk async for chunk in manager.process_turn("Open the door.")]
            assert any(chunk.startswith("event: replay_history") for chunk in chunks)
            assert chunks[-1].startswith("event: error")
            await db.refresh(avatar)
            await db.refresh(state)
            assert avatar.hp == hp and state.in_game_time == world_time
            messages = list(
                await db.scalars(select(ChatMessage).where(ChatMessage.session_id == "session-1"))
            )
            assert len(messages) == 1 and messages[0].content == "Open the door."


async def test_cancelled_normal_turn_recovers_checkpoint(monkeypatch):
    from contextlib import aclosing

    from tests.test_turn_replay import seed as seed_turn

    async def cancelled_cycle(manager, *args, **kwargs):
        await release_for_model(manager)
        manager.avatar.hp -= 10
        await release_for_model(manager)
        yield 'event: status\ndata: {"content":"remote call pending"}\n\n'

    monkeypatch.setattr(GameTurnManager, "_run_llm_cycle", cancelled_cycle)
    async with TestSessionLocal() as db:
        user, avatar, _ = await seed_turn(db)
        hp = avatar.hp
        manager = GameTurnManager(db, "session-1", user)
        async with aclosing(manager.process_turn("Open the door.")) as stream:
            async for chunk in stream:
                if "remote call pending" in chunk:
                    break
        await db.refresh(avatar)
        assert avatar.hp == hp


async def test_container_lookup_preserves_unicode_names_and_session_renames():
    async with TestSessionLocal() as db:
        _, state = await seed(db)
        db.add(
            WorldEntity(
                session_id=state.session_id,
                id="CHEST",
                name="Сундук",
                description="Box",
                entity_type="OBJECT",
                item_type="CONTAINER",
                current_scene_id="START",
            )
        )
        state.entity_states = {"CHEST": {"name": "Кофр"}}
        await db.commit()
        manager = SimpleNamespace(
            db=db, game_id=state.session_id, state=state, avatar=SimpleNamespace(inventory=[])
        )
        for hint in ["сундук", "СуНдУк", "КОФР"]:
            found, _, _ = await ContainerInteractions._resolve_container_target(manager, hint)
            assert found is not None
