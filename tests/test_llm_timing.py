"""Latency instrumentation preserves responses and never stores conversation text."""

import asyncio
from types import SimpleNamespace

import pytest

from backend.core import llm_diagnostics, llm_timing
from backend.core.inference import events, transport
from tests.test_inference_integration import reservations
from tests.test_inference_reservations import router

__all__ = ["reservations"]


def chunk(text=None, **delta):
    return SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=text, **delta))])


async def test_nonstream_keeps_unknown_ttft_and_captures_queue_and_server_measurements(monkeypatch):
    emitted = []
    monkeypatch.setattr(
        llm_diagnostics, "emit", lambda event, **fields: emitted.append((event, fields))
    )

    @llm_diagnostics.async_call("simple")
    async def request(router):
        events.emit("admitted", duration_ms=25)
        llm_timing.dispatched()
        llm_timing.record_response(
            {
                "prompt_eval_duration": 4_000_000,
                "eval_duration": 8_000_000,
                "load_duration": 2_000_000,
                "usage": {"prompt_tokens_details": {"cached_tokens": 100}},
                "SECRET": "PRIVATE_STORY",
            }
        )
        return "PRIVATE_STORY"

    with llm_timing.capture() as records:
        assert await request(SimpleNamespace()) == "PRIVATE_STORY"
    assert records[0]["queue_ms"] == 25
    assert records[0]["prefill_ms"] == 4
    assert records[0]["server_generation_ms"] == 8
    assert records[0]["cached_prompt_tokens"] == 100
    assert "ttft_ms" not in records[0]
    assert "PRIVATE_STORY" not in str(records) + str(emitted)


async def test_stream_ttft_ignores_empty_and_reasoning_only_chunks(monkeypatch):
    now = [10.0]
    monkeypatch.setattr(llm_timing.time, "perf_counter", lambda: now[0])

    @llm_diagnostics.async_call("stream")
    async def request(router):
        llm_timing.dispatched()

        async def output():
            now[0] = 11
            yield chunk(reasoning_content="PRIVATE_REASONING")
            now[0] = 12
            yield chunk("Hello")
            now[0] = 15
            yield chunk(" again")

        return output()

    with llm_timing.capture() as records:
        stream = await request(SimpleNamespace())
        result = [value async for value in stream]
    assert len(result) == 3
    assert records[0]["ttft_ms"] == 2000
    assert records[0]["stream_generation_ms"] == 3000


async def test_parallel_requests_keep_their_measurements_separate():
    entered = asyncio.Event()
    count = 0

    @llm_diagnostics.async_call("structured")
    async def request(router, wait):
        nonlocal count
        count += 1
        if count == 2:
            entered.set()
        await entered.wait()
        llm_timing.queued(wait)
        llm_timing.dispatched()
        return wait

    async def observed(wait):
        with llm_timing.capture() as records:
            assert await request(SimpleNamespace(), wait) == wait
        return records

    first, second = await asyncio.gather(observed(10), observed(20))
    assert first[0]["queue_ms"] == 10 and second[0]["queue_ms"] == 20
    assert len(first) == len(second) == 1


@pytest.mark.parametrize("error", [RuntimeError("PRIVATE"), asyncio.CancelledError()])
async def test_failed_request_keeps_timing_without_replacing_the_error(error):
    @llm_diagnostics.async_call("simple")
    async def request(router):
        raise error

    with llm_timing.capture() as records, pytest.raises(type(error)) as raised:
        await request(SimpleNamespace())
    assert raised.value is error
    assert len(records) == 1 and records[0]["duration_ms"] >= 0
    assert "PRIVATE" not in str(records)


def test_untrusted_provider_values_do_not_become_measurements():
    measurement = llm_timing.Measurement()
    with llm_timing.activate(measurement):
        llm_timing.record_response(
            {
                "prompt_eval_duration": float("nan"),
                "eval_duration": -1,
                "load_duration": True,
                "usage": {"cached_prompt_tokens": "SECRET"},
            }
        )
    assert measurement.provider == {}


def test_extreme_numeric_metadata_cannot_break_the_response():
    measurement = llm_timing.Measurement()
    with llm_timing.activate(measurement):
        llm_timing.record_response(
            {"eval_duration": 10**5000, "usage": {"cached_prompt_tokens": 2.5}}
        )
    assert measurement.provider == {}


async def test_parallel_requests_keep_local_admission_serialized_and_measure_waiting(reservations):
    active, peak = 0, 0

    @transport.guarded_async
    async def sdk(client, kwargs):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.04)
        active -= 1
        return "ok"

    @llm_diagnostics.async_call("simple")
    async def request(client):
        return await sdk(client, {})

    async def measured():
        with llm_timing.capture() as records:
            assert await request(router()) == "ok"
        return records[0]

    rows = await asyncio.gather(measured(), measured())
    assert peak == 1 and reservations.status() == []
    assert max(row["queue_ms"] for row in rows) >= 25
    assert all(row["provider_attempts"] == 1 for row in rows)
