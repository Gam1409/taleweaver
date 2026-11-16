"""Keep SQL generation fences alive until native storage mutations finish."""

import asyncio
from collections.abc import Callable
from typing import ParamSpec, TypeVar

from anyio import CancelScope

P = ParamSpec("P")
T = TypeVar("T")


async def _drain(task: asyncio.Task) -> None:
    with CancelScope(shield=True):
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                continue
            except Exception:
                break
    # Retrieve native errors even when cancellation remains the authoritative result.
    if not task.cancelled():
        task.exception()


async def mutate_storage(operation: Callable[P, T], *args: P.args, **kwargs: P.kwargs) -> T:
    """Cancellation stops the caller only after its uninterruptible write completes.

    asyncio.to_thread cannot stop a running LanceDB mutation. Letting the await
    finish early would release the caller's SQL fence while that write or delete
    can still modify the index. Consequently timeouts may wait for native cleanup.
    Read-only storage operations do not require this protection.
    """
    task = asyncio.create_task(asyncio.to_thread(operation, *args, **kwargs))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        await _drain(task)
        raise
