"""Offload file operations without racing cleanup when a request is cancelled."""

import asyncio
from collections.abc import Callable
from typing import ParamSpec, TypeVar

P = ParamSpec("P")
T = TypeVar("T")


async def run_file_operation(operation: Callable[P, T], *args: P.args, **kwargs: P.kwargs) -> T:
    task = asyncio.create_task(asyncio.to_thread(operation, *args, **kwargs))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        # The worker cannot be interrupted. Keep its files alive until it finishes.
        await asyncio.gather(task, return_exceptions=True)
        raise
