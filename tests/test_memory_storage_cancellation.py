"""A cancelled native mutation must finish before its SQL fence can be released."""

import asyncio
import threading

import pytest
from anyio import CancelScope

from backend.engine.memory_rag.storage_tasks import mutate_storage
from backend.engine.memory_rag.store import LanceMemoryStore, Scope

SCOPE = Scope("owner", "session", 2, "embedding")
MUTATIONS = [
    ("upsert", (SCOPE, [], []), "_upsert"),
    ("prune", (SCOPE, []), "_prune"),
    ("delete_scope", (SCOPE,), "_delete"),
    ("prune_generations", (SCOPE,), "_delete"),
    ("delete_session", ("owner", "session"), "_delete"),
    ("delete_template", ("owner", "template"), "_delete"),
]


def blocking_mutation(started, release, events, *, fail=False):
    loop = asyncio.get_running_loop()

    def operation(*_args):
        loop.call_soon_threadsafe(started.set)
        if not release.wait(5):
            raise AssertionError("Test did not release native storage mutation")
        events.append("native-finished")
        if fail:
            raise OSError("native failure after cancellation")
        return 7

    return operation


@pytest.mark.parametrize("method,args,native", MUTATIONS)
async def test_cancelled_store_mutation_keeps_callers_fence(monkeypatch, method, args, native):
    store = LanceMemoryStore()
    started, release, events = asyncio.Event(), threading.Event(), []
    monkeypatch.setattr(store, native, blocking_mutation(started, release, events))

    async def fenced():
        try:
            await getattr(store, method)(*args)
        finally:
            events.append("fence-released")

    task = asyncio.create_task(fenced())
    try:
        await asyncio.wait_for(started.wait(), 2)
        task.cancel()
        await asyncio.sleep(0.01)
        task.cancel()  # Repeated cancellation must not interrupt cleanup either.
        await asyncio.sleep(0.01)
        assert not task.done()
        assert events == []
    finally:
        release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert events == ["native-finished", "fence-released"]


async def test_anyio_cancellation_drains_mutation_before_scope_exit():
    started, release, events = asyncio.Event(), threading.Event(), []
    scopes = []
    operation = blocking_mutation(started, release, events)

    async def fenced():
        with CancelScope() as scope:
            scopes.append(scope)
            try:
                await mutate_storage(operation)
            finally:
                events.append("fence-released")

    task = asyncio.create_task(fenced())
    try:
        await asyncio.wait_for(started.wait(), 2)
        scopes[0].cancel()
        await asyncio.sleep(0.01)
        assert not task.done()
        assert events == []
    finally:
        release.set()
    await asyncio.wait_for(task, 2)
    assert events == ["native-finished", "fence-released"]


async def test_timeout_does_not_leave_a_late_template_delete(monkeypatch):
    store = LanceMemoryStore()
    started, release, events = asyncio.Event(), threading.Event(), []
    monkeypatch.setattr(store, "_delete", blocking_mutation(started, release, events))
    task = asyncio.create_task(asyncio.wait_for(store.delete_template("owner", "template"), 0.05))
    try:
        await asyncio.wait_for(started.wait(), 2)
        await asyncio.sleep(0.1)
        assert not task.done()
    finally:
        release.set()
    with pytest.raises(TimeoutError):
        await task
    assert events == ["native-finished"]


async def test_native_error_during_cancellation_does_not_replace_cancelled_error():
    started, release, events = asyncio.Event(), threading.Event(), []
    task = asyncio.create_task(
        mutate_storage(blocking_mutation(started, release, events, fail=True))
    )
    try:
        await asyncio.wait_for(started.wait(), 2)
        task.cancel()
        await asyncio.sleep(0)
    finally:
        release.set()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_normal_native_result_and_error_are_preserved():
    assert await mutate_storage(lambda: 7) == 7

    def fail():
        raise OSError("disk failure")

    with pytest.raises(OSError, match="disk failure"):
        await mutate_storage(fail)
