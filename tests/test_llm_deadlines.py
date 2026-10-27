"""Background and foreground operations honor configured role timeouts."""

from types import SimpleNamespace

import pytest

from backend.core.llm_deadlines import role_timeout


@pytest.mark.parametrize("role", ["small", "compression", "complex"])
def test_openai_compatible_deadline_uses_configured_timeout(monkeypatch, role):
    monkeypatch.setattr("backend.core.llm_deadlines.settings.INTELLIGENCE_TIMEOUT", 600)
    user = SimpleNamespace(llm_settings={f"{role}_model_provider": "custom_openai"})
    assert role_timeout(user, role) == 600


@pytest.mark.parametrize("role", ["small", "compression"])
def test_ollama_deadline_uses_requested_role_override(monkeypatch, role):
    monkeypatch.setattr("backend.core.llm_deadlines.settings.INTELLIGENCE_TIMEOUT", 600)
    user = SimpleNamespace(
        llm_settings={
            "small_model_provider": "ollama",
            "small_model": "local-model",
            f"{role}_ollama_timeout": 900,
        }
    )
    assert role_timeout(user, role) == 900


def test_missing_role_preferences_use_application_timeout(monkeypatch):
    monkeypatch.setattr("backend.core.llm_deadlines.settings.INTELLIGENCE_TIMEOUT", 600)
    assert role_timeout(SimpleNamespace(), "small") == 600
