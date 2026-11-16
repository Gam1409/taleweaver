"""Opt-in overlap uses a second durable endpoint reservation, never unguarded calls."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from backend.core.inference.registry import background_call, concurrent_call
from backend.engine.memory_rag.scheduling import scheduler


@asynccontextmanager
async def decision_slot(concurrent: bool) -> AsyncIterator[None]:
    if not concurrent:
        async with scheduler.background():
            yield
        return
    background_token = background_call.set(True)
    concurrent_token = concurrent_call.set(True)
    try:
        yield
    finally:
        concurrent_call.reset(concurrent_token)
        background_call.reset(background_token)
