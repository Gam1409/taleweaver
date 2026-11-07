"""A pending or broken summarizer cannot monopolize raw-history indexing."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.engine.memory_rag import worker
from backend.engine.memory_rag.embeddings import EmbeddingError


def install(monkeypatch):
    user = SimpleNamespace(llm_settings={"memory_rag": {"enabled": True}})
    monkeypatch.setattr(worker, "_load", AsyncMock(return_value=(user, object(), [])))
    monkeypatch.setattr(worker, "_release", AsyncMock())
    monkeypatch.setattr(worker, "_complete", AsyncMock())
    return worker.Claim("session", "owner", 0, 1, "token", None, False)


async def test_pending_summaries_and_vectors_both_advance_in_three_idle_units(monkeypatch):
    claim = install(monkeypatch)
    index = AsyncMock(return_value=True)
    summary = AsyncMock(return_value=True)
    monkeypatch.setattr(worker, "_index_batch", index)
    monkeypatch.setattr(worker, "_summarize", summary)
    for _ in range(3):
        assert await worker._step(claim)
    assert index.await_count == 1
    assert [call.kwargs["chronicle"] for call in summary.call_args_list] == [True, False]


async def test_failed_summary_does_not_prevent_the_next_index_batch(monkeypatch):
    claim = install(monkeypatch)
    index = AsyncMock(side_effect=[False, True])
    summary = AsyncMock(side_effect=RuntimeError("provider unavailable"))
    monkeypatch.setattr(worker, "_index_batch", index)
    monkeypatch.setattr(worker, "_summarize", summary)
    for _ in range(3):
        assert await worker._step(claim)
    assert index.await_count == 2


async def test_failed_embedder_does_not_prevent_chronicle_work(monkeypatch):
    claim = install(monkeypatch)
    index = AsyncMock(side_effect=EmbeddingError("offline"))
    summary = AsyncMock(return_value=True)
    monkeypatch.setattr(worker, "_index_batch", index)
    monkeypatch.setattr(worker, "_summarize", summary)
    for _ in range(2):
        assert await worker._step(claim)
    index.assert_awaited_once()
    summary.assert_awaited_once_with(claim, chronicle=True)


@pytest.mark.parametrize("kind", ["queue", "uncertain", "cancel"])
async def test_admission_and_cancellation_are_never_converted_to_phase_failures(monkeypatch, kind):
    import asyncio

    from backend.core.inference.registry import InferenceQueueError, InferenceUncertainError

    errors = {
        "queue": InferenceQueueError("waiting"),
        "uncertain": InferenceUncertainError("unknown"),
        "cancel": asyncio.CancelledError(),
    }
    claim = install(monkeypatch)
    monkeypatch.setattr(worker, "_index_batch", AsyncMock(side_effect=errors[kind]))
    with pytest.raises(type(errors[kind])):
        await worker._step(claim)
