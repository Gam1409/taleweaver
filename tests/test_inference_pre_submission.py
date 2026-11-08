"""Connection establishment failures cannot leave an inference running remotely."""

import asyncio

import httpx
import pytest

from backend.core.inference import transport
from backend.core.inference.registry import InferenceUncertainError
from backend.engine.memory_rag import embeddings
from backend.engine.memory_rag.settings import MemoryRagSettings
from tests.test_inference_integration import reservations
from tests.test_inference_reservations import URL, router

__all__ = ["reservations"]

NOT_SUBMITTED = [httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout]


@pytest.mark.parametrize("error_type", NOT_SUBMITTED)
async def test_async_connection_establishment_failure_releases_without_retry(
    reservations, error_type
):
    calls = []

    @transport.guarded_async
    async def call(client, args):
        calls.append(args)
        if len(calls) == 1:
            raise error_type("PRIVATE_ENDPOINT")
        return "completed"

    with pytest.raises(error_type):
        await call(router(), {})
    assert len(calls) == 1 and reservations.status() == []
    assert await call(router(), {}) == "completed"
    assert len(calls) == 2 and reservations.status() == []


@pytest.mark.parametrize("error_type", NOT_SUBMITTED)
def test_sync_connection_establishment_failure_releases_without_retry(reservations, error_type):
    @transport.guarded_sync
    def call(client, args):
        raise error_type("PRIVATE_ENDPOINT")

    with pytest.raises(error_type):
        call(router(), {})
    assert reservations.status() == []


@pytest.mark.parametrize("error_type", [httpx.ReadTimeout, httpx.ReadError, httpx.WriteError])
async def test_failure_after_possible_submission_remains_uncertain(reservations, error_type):
    @transport.guarded_async
    async def call(client, args):
        raise error_type("PRIVATE_ENDPOINT")

    with pytest.raises(error_type):
        await call(router(), {})
    with pytest.raises(InferenceUncertainError):
        await call(router(), {})
    assert reservations.status()[0]["status"] == "UNCERTAIN"
    assert "PRIVATE_ENDPOINT" not in str(reservations.status())


async def test_connection_failure_after_recall_stops_waiting_releases_its_exact_lease(
    reservations, monkeypatch
):
    started, release = asyncio.Event(), asyncio.Event()
    monkeypatch.setattr(embeddings, "validate_embedding_url", lambda value: value)

    async def post(client, url, **kwargs):
        started.set()
        await release.wait()
        raise httpx.ConnectError("PRIVATE_ENDPOINT")

    monkeypatch.setattr(httpx.AsyncClient, "post", post)
    config = MemoryRagSettings(
        enabled=True, provider="ollama", model="mock", base_url=URL, timeout_seconds=2
    )
    caller = asyncio.create_task(embeddings.embed_with_settings(config, ["query"], timeout=0.05))
    await started.wait()
    with pytest.raises(embeddings.EmbeddingError):
        await caller
    assert reservations.status()[0]["status"] == "RUNNING"
    release.set()
    for _ in range(100):
        if not reservations.status():
            break
        await asyncio.sleep(0.01)
    assert reservations.status() == []
