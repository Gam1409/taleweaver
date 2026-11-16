"""Serialize NPC bundle publications in the supported single-worker deployment."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from weakref import WeakValueDictionary

_locks: WeakValueDictionary[str, asyncio.Lock] = WeakValueDictionary()


@asynccontextmanager
async def npc_publication_lease(template_id: str) -> AsyncIterator[None]:
    # Retain a strong reference through commit; idle templates do not retain locks.
    lock = _locks.setdefault(template_id, asyncio.Lock())
    async with lock:
        yield
