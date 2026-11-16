"""Heartbeats keep slow model calls alive and never orphan the turn generator."""

import asyncio

import pytest
from anyio import CancelScope

from backend.api.routes.adventures.stream_transport import heartbeat_stream


async def test_heartbeats_do_not_cancel_quiet_provider_and_preserve_events():
    release, closed = asyncio.Event(), asyncio.Event()

    async def source():
        try:
            await release.wait()
            yield 'event: chunk\ndata: {"content":"hello"}\n\n'
            yield 'event: final\ndata: {"status":"success"}\n\n'
        finally:
            closed.set()

    stream = heartbeat_stream(source(), interval=0.01)
    assert await anext(stream) == ": keepalive\n\n"
    assert await anext(stream) == ": keepalive\n\n"
    assert not closed.is_set()
    release.set()
    assert (await anext(stream)).startswith("event: chunk")
    assert (await anext(stream)).startswith("event: final")
    with pytest.raises(StopAsyncIteration):
        await anext(stream)
    assert closed.is_set()


@pytest.mark.parametrize("blocked", [True, False])
async def test_disconnect_closes_source_even_with_buffered_events(blocked):
    closed = asyncio.Event()

    async def source():
        try:
            if blocked:
                await asyncio.Event().wait()
            while True:
                yield "event: chunk\ndata: {}\n\n"
        finally:
            closed.set()

    stream = heartbeat_stream(source(), interval=0.01)
    await anext(stream)
    await asyncio.wait_for(stream.aclose(), 1)
    assert closed.is_set()


async def test_heartbeat_preserves_source_error():
    async def source():
        yield "event: chunk\ndata: {}\n\n"
        raise ValueError("source failed")

    stream = heartbeat_stream(source(), interval=0.01)
    await anext(stream)
    with pytest.raises(ValueError, match="source failed"):
        await anext(stream)


async def test_anyio_disconnect_drains_source_cleanup():
    closed = asyncio.Event()

    async def source():
        try:
            await asyncio.Event().wait()
            yield "unreachable"
        finally:
            await asyncio.sleep(0)
            closed.set()

    with CancelScope() as scope:
        stream = heartbeat_stream(source(), interval=0.01)
        await anext(stream)
        scope.cancel()
        await anext(stream)
    assert closed.is_set()


async def test_chat_route_heartbeat_disconnect_closes_inner_turn(monkeypatch, caplog):
    from functools import partial
    from types import SimpleNamespace

    from backend.api.routes.adventures import gameplay
    from backend.api.routes.adventures.schemas import ChatRequest

    closed = asyncio.Event()

    async def turn(*args, **kwargs):
        try:
            await asyncio.Event().wait()
            yield "unreachable"
        finally:
            closed.set()

    manager = SimpleNamespace(process_turn=turn)
    monkeypatch.setattr(gameplay, "GameTurnManager", lambda *args: manager)
    monkeypatch.setattr(gameplay, "heartbeat_stream", partial(heartbeat_stream, interval=0.01))
    with caplog.at_level("INFO"):
        response = await gameplay.post_chat_message(
            "test-session", ChatRequest(content="hello"), None, None
        )
        assert await anext(response.body_iterator) == ": keepalive\n\n"
        await response.body_iterator.aclose()
    assert closed.is_set()
    assert "final_sent=False" in caplog.text
    assert response.headers["x-taleweaver-turn-id"] in caplog.text
