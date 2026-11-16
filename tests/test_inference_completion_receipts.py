"""A late completion is proof of transport completion, never permission to publish old text."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.core import custom_openai
from backend.core.inference import transport
from backend.core.inference.registry import InferenceQueueError, InferenceUncertainError
from tests.test_inference_integration import real_router, reservations
from tests.test_inference_reservations import router

__all__ = ["reservations"]


async def test_completed_empty_response_does_not_quarantine_the_server(reservations, monkeypatch):
    import openai

    class Client:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

    client, sdk = real_router(monkeypatch, "custom_openai")
    client.api_key = "local-no-key"
    sdk.acompletion = AsyncMock(return_value=SimpleNamespace(choices=[]))
    monkeypatch.setattr(openai, "AsyncOpenAI", Client)
    monkeypatch.setattr(custom_openai, "validate_custom_url", lambda value: value)
    response = await client._acompletion_with_openrouter_fallback({})
    assert response.choices == []
    assert reservations.status() == []


async def test_canceled_caller_keeps_the_request_owned_until_its_receipt(reservations):
    entered, release = asyncio.Event(), asyncio.Event()
    calls = []

    @transport.guarded_async
    async def call(client, args):
        calls.append(args["id"])
        if args["id"] == "old":
            entered.set()
            try:
                await release.wait()
            except asyncio.CancelledError:
                await release.wait()
        return args["id"]

    old = asyncio.create_task(call(router(), {"id": "old"}))
    await entered.wait()
    old.cancel()
    with pytest.raises(asyncio.CancelledError):
        await old
    assert reservations.status()[0]["status"] == "RUNNING"
    current = asyncio.create_task(call(router(), {"id": "current"}))
    await asyncio.sleep(0.04)
    assert calls == ["old"]
    release.set()
    assert await asyncio.wait_for(current, 1) == "current"
    assert old.cancelled()
    assert reservations.status() == []


async def test_unknown_network_failure_still_blocks_retries(reservations):
    entered, release = asyncio.Event(), asyncio.Event()

    @transport.guarded_async
    async def call(client, args):
        entered.set()
        try:
            await release.wait()
        except asyncio.CancelledError:
            await release.wait()
        raise ConnectionError("Connection lost before completion.")

    pending = asyncio.create_task(call(router(), {}))
    await entered.wait()
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending
    release.set()
    for _ in range(10):
        await asyncio.sleep(0.01)
        if reservations.status()[0]["status"] == "UNCERTAIN":
            break
    assert reservations.status()[0]["status"] == "UNCERTAIN"
    with pytest.raises(InferenceUncertainError):
        await call(router(), {})


def test_timeout_reason_and_failure_time_are_persisted_without_error_contents(reservations):
    from tests.test_inference_reservations import KEY

    ticket = reservations.enqueue(KEY)
    assert reservations.try_acquire(ticket)
    reservations.finish(ticket, certain=False, reason="request_timeout")
    stored = json.loads(reservations.path.read_text())[KEY]
    assert stored["reason"] == "request_timeout"
    assert stored["uncertain_at"] >= stored["started"]
    reservations.finish(ticket, certain=False, reason="SECRET_PROVIDER_MESSAGE")
    assert "SECRET_PROVIDER_MESSAGE" not in reservations.path.read_text()


def test_ai_fix_cannot_bypass_a_still_running_request_through_fallback(reservations):
    from backend.api.routes.adventures.editing.ai_fix_fallback import reject_uncertain_fallback
    from tests.test_inference_reservations import KEY

    ticket = reservations.enqueue(KEY)
    assert reservations.try_acquire(ticket)
    with pytest.raises(InferenceQueueError, match="still being monitored"):
        reject_uncertain_fallback(router(), TimeoutError())
    assert reservations.status()[0]["status"] == "RUNNING"
    reservations.finish(ticket, certain=True)
