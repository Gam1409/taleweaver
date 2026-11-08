"""Correlate operation, queue, dispatch and processing failures without recording text."""

import asyncio
import json
from uuid import uuid4

import httpx
import pytest

from backend.core import llm_diagnostics, system_diagnostics
from backend.core.inference import events, transport
from backend.core.inference.registry import InferenceUncertainError
from tests.test_inference_integration import reservations
from tests.test_inference_reservations import KEY, chunk, router

__all__ = ["reservations"]


@pytest.fixture
def trace(tmp_path, monkeypatch):
    service = system_diagnostics.DiagnosticService(tmp_path / "log")
    monkeypatch.setattr(system_diagnostics, "service", service)
    service.set_enabled(True, persist=False)
    yield service
    service.close()


def records(trace):
    return [
        json.loads(line)
        for line in (trace.directory / "system-debug.jsonl").read_text().splitlines()
    ]


def client():
    value = router()
    value.model_category = "complex"
    value.max_tokens = 24576
    value.enable_thinking = True
    return value


async def test_processing_failure_is_distinct_from_completed_transport(trace, reservations):
    @transport.guarded_async
    async def request(value, args):
        await events.sent(httpx.Request("POST", "https://secret.example/v1/chat/completions"))
        return "invalid model JSON"

    @llm_diagnostics.async_call("structured")
    async def structured(value, **kwargs):
        await request(value, {})
        raise ValueError("SECRET_MODEL_CONTENT")

    request_id = str(uuid4())
    with trace.context(request_id=request_id), pytest.raises(ValueError):
        await structured(client(), operation="ai_fix", phase="suggestions")
    data = [row for row in records(trace) if row["event"] != "system.log"]
    chain = [row for row in data if row["event"].startswith(("llm.", "inference."))]
    assert [row["event"] for row in chain] == [
        "llm.started",
        "inference.queued",
        "inference.admitted",
        "inference.sent",
        "inference.completed",
        "llm.failed",
    ]
    assert len({row["call_id"] for row in chain}) == 1
    assert {row["request_id"] for row in chain} == {request_id}
    assert all(row["role"] == "complex" and row["purpose"] == "ai_fix" for row in chain)
    assert chain[0]["max_tokens"] == 24576 and chain[0]["thinking"] is True
    assert chain[-1]["error"]["type"] == "ValueError"
    assert chain[-1]["error"]["frames"][-1]["function"] == "structured"
    text = (trace.directory / "system-debug.jsonl").read_text()
    assert "SECRET_MODEL_CONTENT" not in text and "secret.example" not in text
    assert reservations.status() == []


async def test_blocked_call_is_identifiable_and_never_logged_as_sent(trace, reservations):
    ticket = reservations.enqueue(KEY)
    assert reservations.try_acquire(ticket)
    reservations.finish(ticket, certain=False)

    @transport.guarded_async
    async def request(value, args):
        pytest.fail("A blocked operation must not reach transport.")

    @llm_diagnostics.async_call("structured")
    async def structured(value, **kwargs):
        return await request(value, {})

    with pytest.raises(InferenceUncertainError):
        await structured(client(), operation="ai_fix", phase="suggestions")
    data = [row for row in records(trace) if row["event"].startswith(("llm.", "inference."))]
    assert [row["event"] for row in data] == [
        "llm.started",
        "inference.queued",
        "inference.blocked",
        "llm.failed",
    ]
    assert len({row["call_id"] for row in data}) == 1
    assert data[2]["error"]["type"] == "InferenceUncertainError"


async def test_stream_chain_survives_separate_consumer_tasks(trace, reservations):
    @transport.guarded_async
    async def request(value, args):
        async def output():
            yield chunk()
            yield chunk(True)

        return output()

    @llm_diagnostics.async_call("stream")
    async def streaming(value, **kwargs):
        return await request(value, {"stream": True})

    stream = await streaming(client(), operation="chat_turn", phase="narration")
    await asyncio.wait_for(anext(stream), 1)
    await asyncio.wait_for(anext(stream), 1)
    with pytest.raises(StopAsyncIteration):
        await asyncio.wait_for(anext(stream), 1)
    data = [row for row in records(trace) if row["event"].startswith(("llm.", "inference."))]
    assert len({row["call_id"] for row in data}) == 1
    assert data[-1]["event"] == "llm.completed"
    assert reservations.status() == []
