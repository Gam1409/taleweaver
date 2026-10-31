"""Real admission and fake transports: no inference server is needed."""

import asyncio
import json
from types import SimpleNamespace

import pytest

from backend.core.config import settings
from backend.core.inference import admission, transport
from backend.core.inference.registry import (
    InferenceQueueError,
    InferenceUncertainError,
    Registry,
    background_call,
    endpoint_key,
)

URL = "http://localhost:11434"
KEY = endpoint_key(URL)


@pytest.fixture
def reservations(tmp_path, monkeypatch):
    owner = Registry(tmp_path / "reservations.json")
    monkeypatch.setattr(admission, "_registry", owner)
    monkeypatch.setattr(settings, "INFERENCE_SERIALIZATION_ENABLED", True)
    return owner


def router():
    return SimpleNamespace(provider="ollama", api_base=URL, request_timeout=2)


def chunk(finished=False):
    return SimpleNamespace(choices=[SimpleNamespace(finish_reason="stop" if finished else None)])


def test_origin_identity_groups_models_api_paths_and_loopback_aliases():
    assert endpoint_key("http://127.0.0.1:11434/v1") == KEY
    assert endpoint_key("http://[::1]:11434/api/embed") == KEY
    assert endpoint_key("http://localhost:11435") != KEY
    assert endpoint_key("https://example.org:443/v1") == endpoint_key("https://EXAMPLE.org")


def test_foreground_priority_and_crash_fence_are_durable(reservations):
    token = background_call.set(True)
    background = reservations.enqueue(KEY)
    background_call.reset(token)
    foreground = reservations.enqueue(KEY)
    assert not reservations.try_acquire(background)
    assert reservations.try_acquire(foreground)
    fresh = Registry(reservations.path)
    ticket = fresh.enqueue(KEY)
    with pytest.raises(InferenceUncertainError):
        fresh.try_acquire(ticket)
    with pytest.raises(InferenceQueueError, match="live"):
        reservations.acknowledge_stopped(KEY, foreground.token)
    reservations.finish(foreground, certain=True)
    assert reservations.try_acquire(background)
    reservations.finish(background, certain=True)
    assert reservations.status() == []


async def test_same_endpoint_waits_but_another_server_can_run(reservations):
    entered, release = asyncio.Event(), asyncio.Event()
    order = []

    @transport.guarded_async
    async def call(client, args):
        order.append(args["id"])
        if args["id"] == "first":
            entered.set()
            await release.wait()
        return args["id"]

    first = asyncio.create_task(call(router(), {"id": "first"}))
    await entered.wait()
    second = asyncio.create_task(call(router(), {"id": "second"}))
    other = router()
    other.api_base = "http://localhost:11435"
    assert await call(other, {"id": "other"}) == "other"
    await asyncio.sleep(0.04)
    assert order == ["first", "other"]
    release.set()
    await asyncio.gather(first, second)
    assert order == ["first", "other", "second"]
    assert reservations.status() == []


async def test_cancel_waiter_does_not_quarantine_active_request(reservations):
    first = reservations.enqueue(KEY)
    assert reservations.try_acquire(first)

    async def wait():
        async with admission.reserve(KEY, 2):
            pytest.fail("Cancelled waiter must never submit")

    task = asyncio.create_task(wait())
    await asyncio.sleep(0.03)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert reservations.status()[0]["status"] == "RUNNING"
    assert not reservations.waiters
    reservations.finish(first, certain=True)


@pytest.mark.parametrize("error", [TimeoutError(), asyncio.CancelledError(), ConnectionError()])
async def test_ambiguous_failure_blocks_retry_until_matching_admin_ack(reservations, error):
    calls = 0

    @transport.guarded_async
    async def call(client, args):
        nonlocal calls
        calls += 1
        raise error

    with pytest.raises(type(error)):
        await call(router(), {})
    with pytest.raises(InferenceUncertainError):
        await call(router(), {})
    assert calls == 1
    row = reservations.status()[0]
    assert row["status"] == "UNCERTAIN"
    with pytest.raises(InferenceQueueError):
        reservations.acknowledge_stopped(KEY, "stale-token")
    reservations.acknowledge_stopped(KEY, row["token"])
    assert reservations.status() == []


async def test_explicit_rejection_releases_without_quarantine(reservations):
    class RejectionError(Exception):
        status_code = 400

    @transport.guarded_async
    async def call(client, args):
        raise RejectionError()

    with pytest.raises(RejectionError):
        await call(router(), {})
    assert reservations.status() == []


@pytest.mark.parametrize("finished", [False, True])
async def test_stream_lifetime_and_early_close(reservations, finished):
    closed = asyncio.Event()

    async def chunks():
        try:
            yield chunk(finished)
            await asyncio.Event().wait()
        finally:
            closed.set()

    @transport.guarded_async
    async def call(client, args):
        return chunks()

    stream = await call(router(), {"stream": True})
    assert reservations.status() == []  # Lazy streams have not submitted a request.
    await anext(stream)
    assert reservations.status()[0]["status"] == "RUNNING"
    await stream.aclose()
    assert closed.is_set()
    assert (reservations.status() == []) == finished


async def test_normal_eof_without_finish_reason_remains_uncertain(reservations):
    @transport.guarded_async
    async def call(client, args):
        async def chunks():
            yield chunk()

        return chunks()

    stream = await call(router(), {"stream": True})
    with pytest.raises(InferenceUncertainError, match="completion marker"):
        _ = [item async for item in stream]
    assert reservations.status()[0]["status"] == "UNCERTAIN"


async def test_corrupt_journal_fails_closed_before_transport(reservations):
    reservations.path.write_text("not JSON")

    @transport.guarded_async
    async def call(client, args):
        pytest.fail("Corrupted fencing state must not permit requests")

    with pytest.raises(json.JSONDecodeError):
        await call(router(), {})


async def test_queue_deadline_does_not_mark_waiter_as_remote_work(reservations):
    first = reservations.enqueue(KEY)
    assert reservations.try_acquire(first)
    with pytest.raises(InferenceQueueError, match="Timed out"):
        async with admission.reserve(KEY, 0.01):
            pytest.fail("Busy endpoint must not admit this request")
    assert reservations.status()[0]["token"] == first.token
    assert len(reservations.status()) == 1
    assert not reservations.waiters
    reservations.finish(first, certain=True)


def test_sync_requests_share_durable_registry(reservations):
    @transport.guarded_sync
    def call(client, args):
        assert reservations.status()[0]["status"] == "RUNNING"
        assert args["num_retries"] == 0
        return "done"

    assert call(router(), {}) == "done"
    assert reservations.status() == []


async def test_stream_can_be_consumed_by_separate_timeout_tasks(reservations):
    @transport.guarded_async
    async def call(client, args):
        async def chunks():
            yield chunk()
            yield chunk(True)

        return chunks()

    stream = await call(router(), {"stream": True})
    await asyncio.wait_for(anext(stream), 1)
    await asyncio.wait_for(anext(stream), 1)
    with pytest.raises(StopAsyncIteration):
        await asyncio.wait_for(anext(stream), 1)
    assert reservations.status() == []
    assert admission.request_deadline.get() is None


async def test_sync_thread_holds_reservation_until_remote_call_finishes(reservations):
    import threading

    entered, release = threading.Event(), threading.Event()

    @transport.guarded_sync
    def call(client, args):
        entered.set()
        assert release.wait(timeout=2)
        return "done"

    task = asyncio.create_task(asyncio.to_thread(call, router(), {}))
    assert await asyncio.to_thread(entered.wait, 1)
    assert reservations.status()[0]["status"] == "RUNNING"
    release.set()
    assert await task == "done"
    assert reservations.status() == []


async def test_storage_failure_prevents_unfenced_remote_submission(reservations, monkeypatch):
    def unavailable(records):
        raise OSError("disk unavailable")

    monkeypatch.setattr(reservations, "_write", unavailable)

    @transport.guarded_async
    async def call(client, args):
        pytest.fail("Remote work must not start without a persisted reservation")

    with pytest.raises(OSError):
        await call(router(), {})
    assert not reservations.active
    assert not reservations.waiters


def test_journal_contains_no_endpoint_credentials_or_content(reservations):
    secret_url = "https://secret-user:secret-key@private.example/v1?api_key=other-secret"
    ticket = reservations.enqueue(endpoint_key(secret_url))
    assert reservations.try_acquire(ticket)
    stored = reservations.path.read_text()
    assert "secret" not in stored
    assert "private.example" not in stored
    assert set(json.loads(stored)[ticket.key]) == {"token", "started"}
    reservations.finish(ticket, certain=True)
