"""Unsupported thinking is actionable without exposing provider exception details."""

import pytest

from backend.core.error_diagnostics import diagnose_provider_error


@pytest.mark.parametrize("provider", ["ollama", "ollama_chat", "Ollama"])
def test_unsupported_thinking_explains_role_setting_without_exposing_response(provider):
    error = RuntimeError(
        'OllamaException: {"error":"private-model does not support thinking"} '
        "https://private-host.example token=secret-value"
    )
    message = diagnose_provider_error(error, provider=provider)
    assert "Disable Reasoning / Thinking Mode" in message
    assert "Advanced Parameters" in message
    assert "private-model" not in message
    assert "private-host" not in message
    assert "secret-value" not in message


def test_other_ollama_errors_keep_their_existing_diagnostic():
    message = diagnose_provider_error(RuntimeError("connection refused"), provider="ollama")
    assert "Could not connect" in message
    assert "Disable Reasoning" not in message
