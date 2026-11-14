"""Offload file operations without racing cleanup when a request is cancelled."""

import asyncio
from collections.abc import Callable
from typing import ParamSpec, TypeVar

from anyio import CancelScope

P = ParamSpec("P")
T = TypeVar("T")


async def _drain_file_worker(task: asyncio.Task[T]) -> None:
    finished = asyncio.gather(task, return_exceptions=True)
    while not finished.done():
        try:
            await asyncio.shield(finished)
        except asyncio.CancelledError:
            continue


async def run_file_operation(operation: Callable[P, T], *args: P.args, **kwargs: P.kwargs) -> T:
    task = asyncio.create_task(asyncio.to_thread(operation, *args, **kwargs))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        # The worker cannot be interrupted. Keep its files alive until it finishes.
        with CancelScope(shield=True):
            await _drain_file_worker(task)
        raise
