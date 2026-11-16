"""A short recall deadline must not abandon an already-dispatched embedding response."""

import asyncio

import httpx
import pytest

from backend.core.inference import transport
from backend.engine.memory_rag import embeddings
from backend.engine.memory_rag.settings import MemoryRagSettings
from tests.test_inference_integration import reservations
from tests.test_inference_reservations import KEY, URL, router

__all__ = ["reservations"]


async def test_recall_timeout_keeps_transport_owned_until_late_response_releases_text_queue(
    reservations, monkeypatch
):
    started, release = asyncio.Event(), asyncio.Event()
    submitted, chats = [], []
    monkeypatch.setattr(embeddings, "validate_embedding_url", lambda value: value)

    async def post(client, url, **kwargs):
        submitted.append(client)
        started.set()
        await release.wait()
        assert not client.is_closed
        return httpx.Response(
            200, json={"embeddings": [[1.0, 2.0]]}, request=httpx.Request("POST", url)
        )

    @transport.guarded_async
    async def chat(client, args):
        chats.append(True)
        return "completed"

    monkeypatch.setattr(httpx.AsyncClient, "post", post)
    config = MemoryRagSettings(
        enabled=True, provider="ollama", model="mock", base_url=URL, timeout_seconds=2
    )
    caller = asyncio.create_task(
        embeddings.embed_with_settings(config, ["query"], timeout=0.05, purpose="query")
    )
    await started.wait()
    with pytest.raises(embeddings.EmbeddingError):
        await caller
    assert reservations.status()[0]["status"] == "RUNNING"
    queued_chat = asyncio.create_task(chat(router(), {}))
    await asyncio.sleep(0.01)
    assert not chats
    release.set()
    assert await asyncio.wait_for(queued_chat, 1) == "completed"
    assert len(submitted) == len(chats) == 1 and submitted[0].is_closed
    assert reservations.status() == []


async def test_expired_recall_waiting_for_admission_never_submits_an_embedding(
    reservations, monkeypatch
):
    ticket = reservations.enqueue(KEY)
    assert reservations.try_acquire(ticket)
    submitted = []
    monkeypatch.setattr(embeddings, "validate_embedding_url", lambda value: value)

    async def post(*args, **kwargs):
        submitted.append(True)

    monkeypatch.setattr(httpx.AsyncClient, "post", post)
    config = MemoryRagSettings(
        enabled=True, provider="ollama", model="mock", base_url=URL, timeout_seconds=2
    )
    with pytest.raises(embeddings.EmbeddingError):
        await embeddings.embed_with_settings(config, ["query"], timeout=0.03, purpose="query")
    assert not submitted and len(reservations.status()) == 1
    reservations.finish(ticket, certain=True)
    assert reservations.status() == []


async def test_late_connection_failure_still_requires_verified_recovery(reservations, monkeypatch):
    started, release = asyncio.Event(), asyncio.Event()
    monkeypatch.setattr(embeddings, "validate_embedding_url", lambda value: value)

    async def post(client, url, **kwargs):
        started.set()
        await release.wait()
        raise httpx.ReadError("PRIVATE_ENDPOINT")

    monkeypatch.setattr(httpx.AsyncClient, "post", post)
    config = MemoryRagSettings(
        enabled=True, provider="ollama", model="mock", base_url=URL, timeout_seconds=2
    )
    caller = asyncio.create_task(embeddings.embed_with_settings(config, ["query"], timeout=0.05))
    await started.wait()
    with pytest.raises(embeddings.EmbeddingError):
        await caller
    release.set()
    for _ in range(100):
        if reservations.status()[0]["status"] == "UNCERTAIN":
            break
        await asyncio.sleep(0.01)
    assert reservations.status()[0]["status"] == "UNCERTAIN"
    assert "PRIVATE_ENDPOINT" not in str(reservations.status())
