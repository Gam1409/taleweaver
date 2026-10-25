"""Deletion removes derived memory without erasing detached sessions' story history."""

from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from backend.engine.memory_rag import lifecycle
from backend.engine.memory_rag.documents import collect_documents, sources_hash, validate_candidates
from backend.models.chat import ChatMessage
from backend.models.game_session import GameSession
from backend.models.memory_rag import MemoryIndexState, MemorySummary
from backend.models.session_state import SessionState
from tests.conftest import TestSessionLocal
from tests.test_npc_journal import journal_world, portrait_world, save_message

__all__ = ["journal_world", "portrait_world"]


async def _seed_memory(owner):
    message_id = await save_message("Mira remembered a binding promise.")
    async with TestSessionLocal() as db:
        state = await db.scalar(
            select(SessionState).where(SessionState.session_id == "portrait-session")
        )
        documents = await collect_documents(db, state, owner)
        db.add(
            MemoryIndexState(
                session_id=state.session_id,
                user_id=owner,
                template_id=state.template_id,
                epoch=0,
                lease_token="old-worker",
            )
        )
        db.add(
            MemorySummary(
                session_id=state.session_id,
                user_id=owner,
                layer="story_summary",
                text="Mira's old promise.",
                source_message_ids=[message_id],
                source_hash=sources_hash(documents, [message_id]),
            )
        )
        await db.commit()
    return message_id, documents


async def test_actual_session_delete_purges_owned_vectors_and_canonical_summaries(
    auth_client, journal_world, monkeypatch
):
    owner = journal_world[0]
    await _seed_memory(owner)
    purge = AsyncMock(return_value=3)
    monkeypatch.setattr(lifecycle.LanceMemoryStore, "delete_session", purge)
    foreign = await auth_client.delete("/api/adventures/sessions/other-session")
    assert foreign.status_code == 404
    purge.assert_not_awaited()
    deleted = await auth_client.delete("/api/adventures/sessions/portrait-session")
    assert deleted.status_code == 200
    purge.assert_awaited_once_with(owner, "portrait-session")
    async with TestSessionLocal() as db:
        assert await db.get(GameSession, "portrait-session") is None
        assert await db.get(MemoryIndexState, "portrait-session") is None
        assert await db.scalar(select(MemorySummary.id)) is None
        assert await db.get(GameSession, "other-session") is not None


async def test_optional_vector_cleanup_failure_does_not_block_session_delete(
    auth_client, journal_world, monkeypatch
):
    await _seed_memory(journal_world[0])
    monkeypatch.setattr(
        lifecycle.LanceMemoryStore, "delete_session", AsyncMock(side_effect=RuntimeError("offline"))
    )
    response = await auth_client.delete("/api/adventures/sessions/portrait-session")
    assert response.status_code == 200
    async with TestSessionLocal() as db:
        assert await db.get(MemoryIndexState, "portrait-session") is None


async def test_template_delete_detaches_index_and_preserves_session_history(
    auth_client, journal_world, monkeypatch
):
    owner = journal_world[0]
    message_id, old_documents = await _seed_memory(owner)
    monkeypatch.setattr(
        "backend.engine.media_engine.MediaEngine.cleanup_adventure_assets", AsyncMock()
    )
    response = await auth_client.delete("/api/adventures/portrait-template")
    assert response.status_code == 200, response.text
    async with TestSessionLocal() as db:
        session = await db.get(GameSession, "portrait-session")
        state = await db.scalar(select(SessionState).where(SessionState.session_id == session.id))
        index = await db.get(MemoryIndexState, session.id)
        assert session.template_id is None and state.template_id is None
        assert index.template_id is None and index.epoch == 1 and index.lease_token is None
        assert await db.get(ChatMessage, message_id) is not None
        documents = await collect_documents(db, state, owner)
        assert any(doc.text == "Mira's old promise." for doc in documents)
        old_dialogue = [doc for doc in old_documents if doc.layer == "dialogue"]
        assert await validate_candidates(db, state, owner, old_dialogue) == []


@pytest.mark.parametrize("owner", ["wrong-owner", ""])
async def test_purge_helper_itself_checks_ownership(journal_world, monkeypatch, owner):
    await _seed_memory(journal_world[0])
    purge = AsyncMock()
    monkeypatch.setattr(lifecycle.LanceMemoryStore, "delete_session", purge)
    async with TestSessionLocal() as db:
        await lifecycle.purge_session_memory(db, owner, "portrait-session")
        await db.commit()
        assert await db.get(MemoryIndexState, "portrait-session") is not None
    purge.assert_not_awaited()
