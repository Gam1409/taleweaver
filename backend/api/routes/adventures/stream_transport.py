"""Keep SSE transports alive without extending provider timeouts or losing cleanup."""

import asyncio
from collections.abc import AsyncGenerator
from contextlib import aclosing

from anyio import CancelScope

HEARTBEAT_SECONDS = 15.0


async def _produce(
    source: AsyncGenerator[str, None], queue: asyncio.Queue[str | Exception | None]
) -> None:
    # All reads and finalization stay in the same task, including source contexts.
    async with aclosing(source):
        try:
            async for event in source:
                await queue.put(event)
        except Exception as error:
            await queue.put(error)
            return
    await queue.put(None)


async def _stop(producer: asyncio.Task) -> None:
    producer.cancel()
    with CancelScope(shield=True):
        while not producer.done():
            try:
                await asyncio.shield(producer)
            except asyncio.CancelledError:
                continue
            except Exception:
                break
    if not producer.cancelled():
        producer.exception()


async def heartbeat_stream(
    source: AsyncGenerator[str, None], *, interval: float = HEARTBEAT_SECONDS
) -> AsyncGenerator[str, None]:
    """Emit SSE comments during quiet mechanics/prefill, cancelling work on disconnect."""
    queue: asyncio.Queue[str | Exception | None] = asyncio.Queue(maxsize=1)
    producer = asyncio.create_task(_produce(source, queue))
    try:
        while True:
            try:
                item = await asyncio.wait_for(queue.get(), interval)
            except TimeoutError:
                if producer.done():
                    producer.result()
                    return
                yield ": keepalive\n\n"
                continue
            if item is None:
                return
            if isinstance(item, Exception):
                raise item
            yield item
    finally:
        await _stop(producer)
