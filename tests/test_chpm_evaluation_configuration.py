"""Temporary endpoint tests do not write user settings or query live sessions."""

from unittest.mock import AsyncMock

import pytest

from backend.core import custom_openai
from backend.engine.chpm.evaluation import configuration


async def test_temporary_endpoint_uses_one_discovered_model_without_database(monkeypatch):
    discover = AsyncMock(return_value=["test-model"])
    monkeypatch.setattr(custom_openai, "discover_models", discover)
    monkeypatch.setattr(configuration, "AsyncSessionLocal", lambda: pytest.fail("No DB access"))
    factory = await configuration.factory_for(None, "https://example.org/v1", None)
    small = factory("small")
    complex_model = factory("complex")
    assert small.model == complex_model.model == "test-model"
    assert small.provider == complex_model.provider == "custom_openai"
    assert small.api_base == "https://example.org/v1"
    assert small.user.id is None and small.user.encrypted_api_keys == {}
    assert small.user.llm_settings["custom_openai_url"] == "https://example.org/v1"
    discover.assert_awaited_once()


async def test_model_selection_does_not_guess_when_discovery_is_ambiguous(monkeypatch):
    monkeypatch.setattr(custom_openai, "discover_models", AsyncMock(return_value=["a", "b"]))
    with pytest.raises(ValueError, match="--model"):
        await configuration.factory_for(None, "https://example.org/v1", None)
