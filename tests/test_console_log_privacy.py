"""Ordinary console logs retain counts, without raw model or provider payloads."""

import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.core import llm_logger
from backend.engine import media_generation, media_openrouter
from backend.engine.media_engine import MediaEngine


@pytest.mark.parametrize("mode", ["reported", "estimated", "fallback"])
def test_usage_console_contains_only_numeric_counts(mode, monkeypatch, capsys):
    import litellm

    private = "PRIVATE_MODEL_AND_PROVIDER_FIELD"
    entries = []
    monkeypatch.setattr(llm_logger, "_TELEMETRY_ENABLED", True)
    monkeypatch.setattr(llm_logger, "_write_entry", entries.append)

    def count(**kwargs):
        if mode == "fallback":
            raise ValueError(private)
        return 2 if "messages" in kwargs else 1

    monkeypatch.setattr(litellm, "token_counter", count)
    response = (
        {"usage": {"prompt_tokens": 12, "completion_tokens": private, "total_tokens": 99}}
        if mode == "reported"
        else {}
    )
    llm_logger.log_llm_interaction(
        private, "openai", private, private, private, response, phase=private
    )
    console = capsys.readouterr().out
    assert private not in console
    assert "TOKEN USAGE" in console
    assert "Prompt:" in console
    assert entries[0]["model"] == private  # Explicitly enabled raw telemetry is independent.
    if mode == "reported":
        assert "Prompt: 12 | Completion: 0 | Total: 99" in console


async def test_image_console_does_not_include_raw_model_name(tmp_path, monkeypatch, caplog):
    private = "PRIVATE_IMAGE_MODEL"
    monkeypatch.setattr(media_generation.settings, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(
        media_generation, "_generate_with_provider", AsyncMock(return_value="image.png")
    )
    with caplog.at_level(logging.INFO):
        result = await media_generation.generate_image(
            MediaEngine, "A river", private, None, provider="comfyui"
        )
    assert result == "image.png"
    assert "Generating image" in caplog.text
    assert private not in caplog.text


async def test_openrouter_error_console_does_not_repeat_provider_response(monkeypatch, caplog):
    private = "PRIVATE_PROVIDER_RESPONSE"
    response = SimpleNamespace(
        status_code=400, json=lambda: {"error": {"message": private}}, text=private
    )
    monkeypatch.setattr(media_openrouter.requests, "post", lambda *args, **kwargs: response)
    with caplog.at_level(logging.INFO):
        result, message = await media_openrouter._retry_rejected_dimensions(
            response, {"size": "512x512"}, {}, "model", "A river"
        )
    assert result is response
    assert message == private  # Provider compatibility handling still sees its real error.
    assert "400" in caplog.text
    assert private not in caplog.text
