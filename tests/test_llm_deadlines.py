"""Background and foreground operations honor configured role timeouts."""

from types import SimpleNamespace

import pytest

from backend.core.llm_deadlines import role_timeout


@pytest.mark.parametrize("role", ["small", "compression", "complex"])
def test_cloud_deadline_uses_configured_timeout(monkeypatch, role):
    monkeypatch.setattr("backend.core.llm_deadlines.settings.INTELLIGENCE_TIMEOUT", 600)
    user = SimpleNamespace(llm_settings={f"{role}_model_provider": "openai"})
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


@pytest.mark.parametrize("role", ["small", "compression", "complex", "generator"])
@pytest.mark.parametrize("configured,expected", [(600, 600), (None, 300), (0, 300), (9999, 3600)])
def test_custom_provider_deadline_matches_http_router(monkeypatch, role, configured, expected):
    from backend.core.custom_openai import configure_custom_router

    monkeypatch.setattr("backend.core.llm_deadlines.settings.INTELLIGENCE_TIMEOUT", 60)
    monkeypatch.setattr("backend.core.llm_deadlines.settings.WORLDBUILDING_TIMEOUT", 120)
    monkeypatch.setattr("backend.core.custom_openai.validate_custom_url", lambda value: value)
    # Compression and generator inherit the provider from small when unset.
    settings = {
        "small_model_provider": "custom_openai",
        "custom_openai_url": "http://localhost:5001/v1",
        "custom_openai_timeout": configured,
    }
    user = SimpleNamespace(llm_settings=settings, encrypted_api_keys={})
    router = SimpleNamespace(user=user)
    configure_custom_router(router, settings)
    assert role_timeout(user, role) == router.request_timeout == expected
