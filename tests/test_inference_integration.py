"""Verify the real router, embedding path, scheduler context and admin recovery API."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from backend.core.config import settings
from backend.core.inference import admission, transport
from backend.core.inference.registry import InferenceUncertainError, Registry, background_call
from backend.core.llm_router import GameMasterLLM
from backend.engine.memory_rag import embeddings, scheduling
from backend.engine.memory_rag.settings import MemoryRagSettings
from tests.test_inference_reservations import KEY, URL, chunk, router


@pytest.fixture
def reservations(tmp_path, monkeypatch):
    owner = Registry(tmp_path / "reservations.json")
    monkeypatch.setattr(admission, "_registry", owner)
    monkeypatch.setattr(settings, "INFERENCE_SERIALIZATION_ENABLED", True)
    return owner


def real_router(monkeypatch, provider):
    client = GameMasterLLM.__new__(GameMasterLLM)
    client.provider = provider
    client.api_base = URL
    client.user = SimpleNamespace(id="test")
    client.request_timeout = 2
    sdk = SimpleNamespace(acompletion=AsyncMock(side_effect=TimeoutError("remote unknown")))
    monkeypatch.setattr(client, "_get_litellm", lambda: sdk)
    return client, sdk


async def test_ollama_transport_has_no_hidden_timeout_retries(reservations, monkeypatch):
    client, sdk = real_router(monkeypatch, "ollama")
    with pytest.raises(TimeoutError):
        await client._acompletion_with_openrouter_fallback({"model": "ollama/model"})
    with pytest.raises(InferenceUncertainError):
        await client._acompletion_with_openrouter_fallback({"model": "ollama/other-role"})
    assert sdk.acompletion.await_count == 1
    assert sdk.acompletion.call_args.kwargs["num_retries"] == 0


async def test_custom_adapter_cannot_bypass_shared_origin(reservations, monkeypatch):
    from backend.core import custom_openai

    client, _ = real_router(monkeypatch, "custom_openai")
    mocked = AsyncMock(return_value="completed")
    monkeypatch.setattr(custom_openai, "acomplete", mocked)
    assert await client._acompletion_with_openrouter_fallback({}) == "completed"
    ticket = reservations.enqueue(KEY)
    assert reservations.try_acquire(ticket)
    reservations.finish(ticket, certain=False)
    with pytest.raises(InferenceUncertainError):
        await client._acompletion_with_openrouter_fallback({})
    assert mocked.await_count == 1


async def test_embedding_cannot_overlap_text_on_same_ollama(reservations, monkeypatch):
    monkeypatch.setattr(embeddings, "validate_embedding_url", lambda value: value)
    calls = []

    async def post(client, url, **kwargs):
        calls.append(url)
        return httpx.Response(
            200, json={"embeddings": [[1.0, 2.0]]}, request=httpx.Request("POST", url)
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", post)
    ticket = reservations.enqueue(KEY)
    assert reservations.try_acquire(ticket)
    config = MemoryRagSettings(enabled=True, provider="ollama", model="bge-m3", base_url=URL)
    task = asyncio.create_task(embeddings.embed_with_settings(config, ["fact"]))
    await asyncio.sleep(0.05)
    assert not calls
    reservations.finish(ticket, certain=True)
    assert await task == [[1.0, 2.0]]
    assert reservations.status() == []


async def test_scheduler_context_and_background_recheck(reservations, monkeypatch):
    scheduler = scheduling.IdleScheduler(grace_seconds=0)
    monkeypatch.setattr(scheduling, "scheduler", scheduler)
    assert not background_call.get()
    async with scheduler.background():
        assert background_call.get()
        ticket = reservations.enqueue(KEY)
        async with scheduler.foreground():
            assert not background_call.get()
            assert not admission.ready(ticket)
        assert background_call.get()
        reservations.forget(ticket)
    assert not background_call.get()


async def test_late_result_after_cancellation_is_never_delivered(reservations):
    started, finish = asyncio.Event(), asyncio.Event()
    late = asyncio.Event()

    @transport.guarded_async
    async def call(client, args):
        started.set()
        try:
            await finish.wait()
        except asyncio.CancelledError:
            await finish.wait()
        late.set()
        return "late decision"

    task = asyncio.create_task(call(router(), {}))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert reservations.status()[0]["status"] == "UNCERTAIN"
    finish.set()
    await late.wait()
    assert reservations.status()[0]["status"] == "UNCERTAIN"


async def test_closing_filtered_stream_releases_all_layers_immediately(reservations):
    async def chunks():
        yield chunk()
        await asyncio.Event().wait()

    @transport.guarded_async
    async def call(client, args):
        return chunks()

    async def passthrough(source):
        async for item in source:
            yield item

    raw = await call(router(), {"stream": True})
    filtered = passthrough(raw)
    output = transport.owned_stream(filtered, raw)
    await anext(output)
    await output.aclose()
    assert reservations.status()[0]["status"] == "UNCERTAIN"


async def test_admin_recovery_requires_confirmation_and_current_token(auth_client, reservations):
    ticket = reservations.enqueue(KEY)
    assert reservations.try_acquire(ticket)
    path = "/api/inference-queue"
    status = await auth_client.get(path)
    assert status.status_code == 200
    payload = {"endpoint_id": KEY, "token": ticket.token}
    assert (await auth_client.post(path + "/acknowledge-stopped", json=payload)).status_code == 422
    payload["confirmation"] = "REMOTE_GENERATION_STOPPED"
    assert (await auth_client.post(path + "/acknowledge-stopped", json=payload)).status_code == 409
    reservations.finish(ticket, certain=False)
    assert (await auth_client.post(path + "/acknowledge-stopped", json=payload)).status_code == 200
    assert (await auth_client.post(path + "/acknowledge-stopped", json=payload)).status_code == 409


async def test_disabled_guard_preserves_existing_transport(monkeypatch, reservations):
    monkeypatch.setattr(settings, "INFERENCE_SERIALIZATION_ENABLED", False)

    @transport.guarded_async
    async def call(client, args):
        assert "num_retries" not in args
        return "original"

    assert await call(router(), {}) == "original"
    assert not reservations.path.exists()


async def test_non_admin_cannot_view_or_clear_queue(auth_client, reservations):
    from sqlalchemy import select

    from backend.models.user import User
    from tests.conftest import TestSessionLocal

    async with TestSessionLocal() as db:
        user = await db.scalar(select(User))
        user.role = "user"
        await db.commit()
    assert (await auth_client.get("/api/inference-queue")).status_code == 403
    response = await auth_client.post(
        "/api/inference-queue/acknowledge-stopped",
        json={"endpoint_id": KEY, "token": "old", "confirmation": "REMOTE_GENERATION_STOPPED"},
    )
    assert response.status_code == 403


async def test_queue_time_reduces_provider_timeout(reservations, monkeypatch):
    client, sdk = real_router(monkeypatch, "ollama")
    sdk.acompletion = AsyncMock(return_value="done")
    ticket = reservations.enqueue(KEY)
    assert reservations.try_acquire(ticket)
    task = asyncio.create_task(client._acompletion_with_openrouter_fallback({}))
    await asyncio.sleep(0.06)
    reservations.finish(ticket, certain=True)
    assert await task == "done"
    assert 0 < sdk.acompletion.call_args.kwargs["request_timeout"] < 1.96
    assert admission.request_deadline.get() is None
