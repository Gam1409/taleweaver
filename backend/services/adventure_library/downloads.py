"""Bounded HTTPS reads for a configured catalog; remote redirects are never followed."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx

CHUNK_SIZE = 64 * 1024
FETCH_TIMEOUT = httpx.Timeout(30.0, connect=10.0)


class LibraryError(Exception):
    """The configured catalog cannot be read safely or is unavailable."""


class ByteBudget:
    def __init__(self, limit: int):
        self.limit = limit
        self.used = 0

    def take(self, size: int) -> None:
        self.used += size
        if self.used > self.limit:
            raise LibraryError(f"Download exceeds the {self.limit} byte limit")


@asynccontextmanager
async def client_context(injected: httpx.AsyncClient | None) -> AsyncIterator[httpx.AsyncClient]:
    if injected is not None:
        yield injected
        return
    async with httpx.AsyncClient(timeout=FETCH_TIMEOUT, follow_redirects=False) as client:
        yield client


async def fetch_bytes(
    client: httpx.AsyncClient, url: str, budget: ByteBudget, file_limit: int
) -> bytes:
    chunks = []
    received = 0
    try:
        async with client.stream("GET", url, follow_redirects=False) as response:
            if response.status_code != httpx.codes.OK:
                raise LibraryError(f"Unexpected HTTP status {response.status_code}")
            async for chunk in response.aiter_bytes(CHUNK_SIZE):
                received += len(chunk)
                budget.take(len(chunk))
                if received > file_limit:
                    raise LibraryError(f"File exceeds the {file_limit} byte limit")
                chunks.append(chunk)
    except httpx.HTTPError as exc:
        raise LibraryError(f"Request failed: {exc.__class__.__name__}") from exc
    return b"".join(chunks)
