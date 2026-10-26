"""Embedding-only HTTP clients, deliberately independent from completion routing."""

import asyncio
import ipaddress
import math
from typing import Any
from urllib.parse import urlsplit

import httpx

from backend.core.llm_diagnostics import async_operation
from backend.engine.memory_rag.settings import MemoryRagSettings, read_settings
from backend.utils.path_security import _resolve_host_ips, validate_provider_url

MAX_BATCH_SIZE = 64
MAX_TEXT_LENGTH = 16_000
MAX_DIMENSION = 16_384


class EmbeddingError(ValueError):
    """A safe, actionable embedding failure without provider payloads or credentials."""


def validate_embedding_url(base_url: str) -> str:
    normalized = validate_provider_url(base_url).rstrip("/")
    addresses = _resolve_host_ips(urlsplit(normalized).hostname)
    if not addresses:
        raise EmbeddingError("Could not resolve embedding endpoint hostname.")
    for address in addresses:
        ip = ipaddress.ip_address(address)
        forbidden = ip.is_link_local or ip.is_multicast or ip.is_unspecified
        if (
            forbidden
            or (ip.is_reserved and not ip.is_loopback)
            or str(ip) in {"100.100.100.200", "fd00:ec2::254"}
        ):
            raise EmbeddingError(
                "Metadata, link-local, reserved and multicast endpoints are forbidden."
            )
    return normalized


def validate_vectors(vectors: Any, count: int) -> list[list[float]]:
    if not isinstance(vectors, list) or len(vectors) != count:
        raise EmbeddingError("Embedding response count does not match input count.")
    result = [_validate_vector(vector) for vector in vectors]
    if result and any(len(vector) != len(result[0]) for vector in result):
        raise EmbeddingError("Embedding response dimensions are inconsistent.")
    return result


def _validate_vector(vector: Any) -> list[float]:
    if not isinstance(vector, list) or not 1 <= len(vector) <= MAX_DIMENSION:
        raise EmbeddingError("Embedding dimension is empty or exceeds the supported limit.")
    if any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in vector):
        raise EmbeddingError("Embedding values must be numeric.")
    try:
        values = [float(value) for value in vector]
    except (OverflowError, ValueError) as exc:
        raise EmbeddingError("Embedding values must be finite.") from exc
    if not all(math.isfinite(value) for value in values):
        raise EmbeddingError("Embedding values must be finite.")
    return values


def _parse_vectors(payload: Any, provider: str, count: int) -> list[list[float]]:
    if not isinstance(payload, dict):
        raise EmbeddingError("Embedding endpoint returned an invalid object.")
    if provider == "ollama":
        return validate_vectors(payload.get("embeddings"), count)
    data = payload.get("data")
    if not isinstance(data, list) or len(data) != count:
        raise EmbeddingError("Embedding endpoint returned invalid data.")
    if any(not isinstance(item, dict) for item in data):
        raise EmbeddingError("Embedding endpoint returned invalid data.")
    indices = [item.get("index") for item in data]
    if any(type(index) is not int for index in indices) or sorted(indices) != list(range(count)):
        raise EmbeddingError("Embedding endpoint returned invalid indices.")
    return validate_vectors(
        [item.get("embedding") for item in sorted(data, key=lambda x: x["index"])], count
    )


def _request_url(settings: MemoryRagSettings, base: str) -> str:
    if settings.provider == "ollama":
        return f"{base}/embed" if base.endswith("/api") else f"{base}/api/embed"
    return f"{base}/embeddings" if base.endswith("/v1") else f"{base}/v1/embeddings"


async def embed_texts(
    user: Any, texts: list[str], *, timeout: float | None = None
) -> list[list[float]]:
    settings = read_settings(user)
    return await embed_with_settings(
        settings, texts, api_key=_credential_key(user), timeout=timeout
    )


@async_operation("embedding")
async def embed_with_settings(
    settings: MemoryRagSettings,
    texts: list[str],
    *,
    api_key: str = "",
    timeout: float | None = None,
) -> list[list[float]]:
    if not settings.enabled or not settings.base_url or not settings.model:
        raise EmbeddingError("Enable memory and configure an embedding URL and model first.")
    if not texts:
        return []
    if len(texts) > MAX_BATCH_SIZE or any(
        not isinstance(t, str) or not t.strip() or len(t) > MAX_TEXT_LENGTH for t in texts
    ):
        raise EmbeddingError("Embedding input is empty or exceeds batch/text limits.")
    duration = (
        settings.timeout_seconds if timeout is None else min(settings.timeout_seconds, timeout)
    )
    if not math.isfinite(duration) or duration <= 0:
        raise EmbeddingError("Embedding request timeout must be positive and finite.")
    try:
        return await asyncio.wait_for(_embed(settings, texts, duration, api_key), timeout=duration)
    except (httpx.HTTPError, asyncio.TimeoutError, ValueError) as exc:
        if isinstance(exc, EmbeddingError):
            raise
        raise EmbeddingError(
            "Embedding request failed; check the endpoint, model and credentials."
        ) from exc


async def _embed(
    settings: MemoryRagSettings, texts: list[str], duration: float, api_key: str
) -> list[list[float]]:
    base = await asyncio.to_thread(validate_embedding_url, settings.base_url)
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    body = {"model": settings.model, "input": texts}
    async with httpx.AsyncClient(timeout=duration, follow_redirects=False) as client:
        response = await client.post(_request_url(settings, base), json=body, headers=headers)
    response.raise_for_status()
    return _parse_vectors(response.json(), settings.provider, len(texts))


def _credential_key(user: Any) -> str:
    encrypted = (getattr(user, "encrypted_api_keys", None) or {}).get("memory_embeddings")
    if not encrypted:
        return ""
    from backend.core.security import encryption_util

    return encryption_util.decrypt_key(encrypted)
