"""Connection tests report safe, actionable errors instead of a generic UI failure."""

from unittest.mock import AsyncMock

import httpx
import pytest

from backend.api.routes import memory_settings
from backend.engine.memory_rag.diagnostics import embedding_test_diagnostic
from backend.engine.memory_rag.embeddings import EmbeddingError

CONFIG = {
    "enabled": True,
    "provider": "ollama",
    "base_url": "http://127.0.0.1:11434",
    "model": "bge-m3",
    "timeout_seconds": 60,
}


def wrapped(cause: Exception) -> EmbeddingError:
    error = EmbeddingError("Embedding request failed; check the endpoint, model and credentials.")
    error.__cause__ = cause
    return error


@pytest.mark.parametrize(
    "cause,expected",
    [
        (TimeoutError("secret"), "timed out"),
        (httpx.ReadTimeout("secret"), "timed out"),
        (httpx.ConnectError("secret"), "backend could not communicate"),
        (
            ValueError(
                "URL points to a private/loopback address. Set "
                "ALLOW_PRIVATE_NETWORK_MODELS=true to allow local providers."
            ),
            "ALLOW_PRIVATE_NETWORK_MODELS=true",
        ),
        (RuntimeError("secret"), "Check the endpoint"),
    ],
)
def test_chained_error_is_classified_without_exposing_exception(cause, expected):
    message = embedding_test_diagnostic(wrapped(cause))
    assert expected in message
    assert "secret" not in message


@pytest.mark.parametrize(
    "status,expected",
    [(401, "denied access"), (404, "HTTP 404"), (429, "rate-limiting"), (500, "HTTP error")],
)
def test_provider_response_and_request_details_remain_private(status, expected):
    response = httpx.Response(
        status,
        text="private response",
        request=httpx.Request("POST", "http://private-host/api/embed?token=secret"),
    )
    error = httpx.HTTPStatusError("secret", request=response.request, response=response)
    message = embedding_test_diagnostic(wrapped(error))
    assert expected in message
    assert "private" not in message
    assert "secret" not in message


async def test_timeout_reaches_ui_result_without_saving_settings(auth_client, monkeypatch):
    monkeypatch.setattr(
        memory_settings,
        "embed_with_settings",
        AsyncMock(side_effect=wrapped(httpx.ReadTimeout("private provider response"))),
    )
    result = await auth_client.post("/api/settings/memory-rag/test", json=CONFIG)
    assert result.status_code == 200
    assert result.json()["ok"] is False
    assert "timed out" in result.json()["message"]
    assert "private" not in result.text
    saved = await auth_client.get("/api/settings/memory-rag")
    assert saved.json()["enabled"] is False


async def test_successful_ollama_vectors_keep_existing_response(auth_client, monkeypatch):
    embed = AsyncMock(return_value=[[0.1] * 1024])
    monkeypatch.setattr(memory_settings, "embed_with_settings", embed)
    result = await auth_client.post("/api/settings/memory-rag/test", json=CONFIG)
    assert result.status_code == 200
    assert result.json()["ok"] is True
    assert result.json()["dimensions"] == 1024
    assert embed.await_args.args[0].model == "bge-m3"
