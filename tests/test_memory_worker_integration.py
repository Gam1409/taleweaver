"""Real SQLite-to-Lance indexing and recall with only model traffic mocked."""

import math
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from backend.engine.memory_rag import retrieval, worker
from backend.engine.memory_rag.documents import collect_documents
from backend.engine.memory_rag.scheduling import IdleScheduler
from backend.engine.memory_rag.settings import embedding_signature, read_settings
from backend.engine.memory_rag.store import LanceMemoryStore, Scope
from backend.models.chat import ChatMessage
from backend.models.memory_rag import MemoryIndexState
from backend.models.session_state import SessionState
from backend.models.user import User
from tests.conftest import TestSessionLocal
from tests.test_npc_journal import journal_world, portrait_world, save_message

__all__ = ["journal_world", "portrait_world"]


async def _seed_index(owner):
    for number in range(18):
        await save_message(f"The traveler recorded ordinary event {number}.")
    message_id = await save_message("A long journey. " * 1200 + "Mira prefers violet biscuits.")
    async with TestSessionLocal() as db:
        user = await db.get(User, owner)
        user.llm_settings = {
            "memory_rag": {
                "enabled": True,
                "base_url": "http://localhost:11434",
                "model": "test-embed",
            }
        }
        state = await db.scalar(
            select(SessionState).where(SessionState.session_id == "portrait-session")
        )
        await worker.mark_dirty(db, state.session_id, owner, state.template_id)
        await db.flush()
        index = await db.get(MemoryIndexState, state.session_id)
        index.epoch = 1
        await db.commit()
        documents = await collect_documents(db, state, owner)
        return message_id, documents


async def _assert_recall(owner):
    async with TestSessionLocal() as db:
        user = await db.get(User, owner)
        state = await db.scalar(
            select(SessionState).where(SessionState.session_id == "portrait-session")
        )
        index = await db.get(MemoryIndexState, state.session_id)
        assert index.status == "ready"
        assert index.indexed_revision == index.desired_revision > 0
        assert index.signature == embedding_signature(read_settings(user), 2)
        assert index.lease_token is None
        manager = SimpleNamespace(db=db, state=state, user=user)
        recall = await retrieval.prepare_recall(manager, "What biscuits does Mira prefer?", [])
        assert recall.method == "hybrid"
        assert any("violet biscuits" in document.text for document in recall.documents)


async def test_worker_batches_real_index_reclaims_old_epoch_and_recalls_tail_fact(
    journal_world, monkeypatch, tmp_path
):
    pytest.importorskip("lancedb")
    owner, _ = journal_world
    monkeypatch.setenv("MEMORY_DB_DIR", str(tmp_path / "memory"))
    monkeypatch.setattr(worker, "scheduler", IdleScheduler(grace_seconds=0))
    monkeypatch.setattr(worker, "_summarize", AsyncMock(return_value=False))
    message_id, documents = await _seed_index(owner)
    store = LanceMemoryStore()
    old_scope = Scope(owner, "portrait-session", 0, "old-embedding-space")
    await store.upsert(old_scope, [documents[0].to_dict()], [[0.0, 1.0]])
    batch_sizes = []

    async def embed(user, texts, **kwargs):
        batch_sizes.append(len(texts))
        assert all(len(text) <= worker.MAX_TEXT_LENGTH for text in texts)
        return [[1.0, 0.0] if "violet biscuits" in text else [0.0, 1.0] for text in texts]

    monkeypatch.setattr(worker, "embed_texts", embed)
    monkeypatch.setattr(retrieval, "embed_texts", AsyncMock(return_value=[[1.0, 0.0]]))
    await worker._run("portrait-session", owner)
    assert len(batch_sizes) == math.ceil(len(documents) / worker.BATCH_SIZE)
    assert max(batch_sizes) == worker.BATCH_SIZE
    assert await store.list_document_hashes(old_scope) == {}
    await _assert_recall(owner)

    async with TestSessionLocal() as db:
        message = await db.get(ChatMessage, message_id)
        message.content += " She shares them with her friends."
        await worker.mark_dirty(db, "portrait-session", owner, documents[0].template_id)
        await db.commit()
    initial_batches = len(batch_sizes)
    await worker._run("portrait-session", owner)
    assert len(batch_sizes) > initial_batches
    await _assert_recall(owner)
