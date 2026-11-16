"""Blocking file workers must leave the event loop responsive and finish before cleanup."""

import asyncio
import threading

import pytest

from backend.utils.async_files import run_file_operation


@pytest.mark.asyncio
async def test_worker_does_not_block_loop():
    loop_thread = threading.get_ident()
    worker_thread = await run_file_operation(threading.get_ident)
    assert worker_thread != loop_thread


@pytest.mark.asyncio
async def test_cancellation_waits_for_file_worker():
    loop = asyncio.get_running_loop()
    started = asyncio.Event()
    release = threading.Event()
    finished = threading.Event()

    def operation():
        loop.call_soon_threadsafe(started.set)
        assert release.wait(5)
        finished.set()

    task = asyncio.create_task(run_file_operation(operation))
    try:
        await asyncio.wait_for(started.wait(), 2)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
    finally:
        release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert finished.is_set()
