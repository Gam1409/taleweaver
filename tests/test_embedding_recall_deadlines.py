"""Configured embedding deadlines govern both public and observer recall."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from backend.engine.chpm import semantic_recall
from backend.engine.chpm.runtime import Turn
from backend.engine.chpm.schema import KernelState, Settings
from backend.engine.memory_rag import retrieval
from backend.engine.memory_rag.settings import MemoryRagSettings, embedding_signature
from tests.test_chpm_kernel import observation
from tests.test_memory_rag_retrieval import manager


def test_new_timeout_default_preserves_explicit_legacy_settings_and_vector_space():
    assert MemoryRagSettings().timeout_seconds == 30
    legacy = MemoryRagSettings(timeout_seconds=10)
    assert legacy.timeout_seconds == 10
    assert embedding_signature(legacy, 2) == embedding_signature(
        legacy.model_copy(update={"timeout_seconds": 30}), 2
    )


async def test_public_recall_keeps_a_response_slower_than_the_old_fixed_cutoff(monkeypatch):
    host = manager()
    host.user.llm_settings["memory_rag"]["timeout_seconds"] = 3
    config = retrieval.read_settings(host.user)
    signature = embedding_signature(config, 2)
    host.db.scalar.return_value = SimpleNamespace(
        paused=False,
        signature=signature,
        indexed_revision=1,
        template_id="template",
        epoch=3,
    )

    async def delayed_embedding(*args, **kwargs):
        assert kwargs["timeout"] == 3
        await asyncio.sleep(1.6)
        return [[1.0, 0.0]]

    query = AsyncMock(return_value=[])
    monkeypatch.setattr(retrieval, "embed_texts", delayed_embedding)
    monkeypatch.setattr(retrieval.LanceMemoryStore, "query", query)
    _, scope = await retrieval._semantic_candidates(host, "Where is the sample?")
    assert scope is not None and scope.signature == signature
    query.assert_awaited_once()


async def test_observer_recall_uses_the_same_configured_wait(monkeypatch):
    host = manager()
    host.user.llm_settings["memory_rag"]["timeout_seconds"] = 3
    turn = Turn(
        KernelState(settings=Settings(mode="live", actor_ids=["npc"], semantic_memory=True)),
        "input",
    )

    async def delayed_read(manager, target, actors, observed):
        await asyncio.sleep(2.1)
        target.usage.semantic_recall = {"npc": "no_matches"}

    monkeypatch.setattr(semantic_recall, "_read", delayed_read)
    await semantic_recall.prepare(host, turn, ["npc"], observation())
    assert turn.usage.semantic_recall == {"npc": "no_matches"}
