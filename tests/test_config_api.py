"""
Tests for the Settings / Config REST API (Package 4).

Covers: saving encrypted API keys for different providers.
"""

from typing import Optional

import pytest
import pytest_asyncio
from httpx import AsyncClient

from backend.api.routes import config_api
from backend.core.auth import create_access_token, get_password_hash
from backend.models.user import User
from tests.conftest import TestSessionLocal
from tests.llm_fakes import RoleLLMFactory

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def client(auth_client: AsyncClient) -> AsyncClient:
    """Settings endpoints require authentication."""
    return auth_client


async def test_save_api_key_creates_user(client: AsyncClient):
    """
    Saving an API key for the first time creates the default user
    and returns a success status.
    """
    # Arrange
    payload = {"provider": "openai", "api_key": "sk-test-key-123"}

    # Act
    resp = await client.post("/api/settings/keys", json=payload)

    # Assert
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "success"
    assert "openai" in data["message"]


async def test_save_api_key_multiple_providers(client: AsyncClient):
    """Saving keys for two providers both succeed independently."""
    for provider, key in [("openai", "sk-openai"), ("anthropic", "sk-anthropic")]:
        resp = await client.post(
            "/api/settings/keys",
            json={"provider": provider, "api_key": key},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "success"


async def test_save_api_key_overwrites_existing(client: AsyncClient):
    """Saving a key for the same provider twice overwrites the first key."""
    payload = {"provider": "openai", "api_key": "sk-first"}
    await client.post("/api/settings/keys", json=payload)

    payload["api_key"] = "sk-second"
    resp = await client.post("/api/settings/keys", json=payload)
    assert resp.status_code == 200
    assert resp.json()["status"] == "success"


async def test_save_t2i_settings_with_ollama_fields(client: AsyncClient):
    """Saving Ollama image settings persists optional local generation controls."""
    payload = {
        "simple_model": "x/flux2-klein",
        "simple_model_provider": "ollama",
        "advanced_model": "x/flux2-klein",
        "advanced_model_provider": "ollama",
        "provider": "ollama",
        "ollama_url": "http://localhost:11434",
        "width": 1024,
        "height": 768,
        "steps": 30,
        "seed": 42,
        "image_format": "jpeg",
        "image_quality": 85,
        "negative_prompt": "blurry, artifacts",
    }

    save_resp = await client.post("/api/settings/t2i", json=payload)
    assert save_resp.status_code == 200
    assert save_resp.json()["status"] == "success"

    settings_resp = await client.get("/api/settings")
    assert settings_resp.status_code == 200
    data = settings_resp.json()
    t2i = data["t2i_settings"]
    for k, v in payload.items():
        assert t2i[k] == v


async def test_get_settings_returns_extended_t2i_defaults(client: AsyncClient):
    """Default settings include Ollama-compatible fields for forward compatibility."""
    from sqlalchemy import update

    async with TestSessionLocal() as session:
        await session.execute(
            update(User)
            .where(User.username == "test_user")
            .values(llm_settings=None, t2i_settings=None)
        )
        await session.commit()

    resp = await client.get("/api/settings")
    assert resp.status_code == 200
    data = resp.json()
    assert "t2i_settings" in data

    t2i = data["t2i_settings"]
    assert t2i["simple_model"] == ""
    assert t2i["advanced_model"] == ""
    assert t2i["provider"] == "openai"
    assert t2i["simple_model_provider"] == "openai"
    assert t2i["advanced_model_provider"] == "openai"
    assert t2i["ollama_url"] == "http://localhost:11434"
    assert t2i["width"] is None
    assert t2i["height"] is None
    assert t2i["steps"] is None
    assert t2i["seed"] is None
    assert t2i["negative_prompt"] is None


async def test_save_llm_settings_with_ollama_url(client: AsyncClient):
    """Saving LLM settings should persist local Ollama endpoint configuration."""
    payload = {
        "small_model": "llama3.2",
        "small_model_provider": "ollama",
        "complex_model": "qwen2.5",
        "complex_model_provider": "ollama",
        "generator_model": "llama3-70b",
        "generator_model_provider": "ollama",
        "preferred_provider": "ollama",
        "ollama_url": "http://localhost:11434",
    }

    save_resp = await client.post("/api/settings/llm", json=payload)
    assert save_resp.status_code == 200
    assert save_resp.json()["status"] == "success"

    settings_resp = await client.get("/api/settings")
    assert settings_resp.status_code == 200
    llm = settings_resp.json()["llm_settings"]
    assert llm["small_model"] == "llama3.2"
    assert llm["small_model_provider"] == "ollama"
    assert llm["complex_model"] == "qwen2.5"
    assert llm["complex_model_provider"] == "ollama"
    assert llm["preferred_provider"] == "ollama"
    assert llm["ollama_url"] == "http://localhost:11434"


async def test_save_llm_settings_normalizes_openrouter_models(client: AsyncClient):
    """OpenRouter LLM settings should not store stale provider prefixes."""
    payload = {
        "small_model": "openai/gpt-oss-120b",
        "small_model_provider": "openrouter",
        "complex_model": "openai/gpt-5.4",
        "complex_model_provider": "openrouter",
        "generator_model": "anthropic/claude-3-opus",
        "generator_model_provider": "openrouter",
        "preferred_provider": "openrouter",
        "ollama_url": "http://localhost:11434",
    }

    save_resp = await client.post("/api/settings/llm", json=payload)
    assert save_resp.status_code == 200
    assert save_resp.json()["status"] == "success"

    settings_resp = await client.get("/api/settings")
    assert settings_resp.status_code == 200
    data = settings_resp.json()["llm_settings"]
    assert data["small_model"] == "openai/gpt-oss-120b"
    assert data["complex_model"] == "openai/gpt-5.4"
    assert data["preferred_provider"] == "openrouter"
    assert data["ollama_url"] == "http://localhost:11434"


async def test_get_settings_returns_llm_ollama_default(client: AsyncClient):
    """Default llm settings include ollama_url for local provider use."""
    from sqlalchemy import update

    async with TestSessionLocal() as session:
        await session.execute(
            update(User)
            .where(User.username == "test_user")
            .values(llm_settings=None, t2i_settings=None)
        )
        await session.commit()

    resp = await client.get("/api/settings")
    assert resp.status_code == 200
    llm = resp.json()["llm_settings"]
    assert llm["small_model_provider"] == "openai"
    assert llm["complex_model_provider"] == "openai"
    assert llm["small_max_tokens"] == 12288
    assert llm["complex_max_tokens"] == 24576
    assert llm["play_agent_model"] == ""
    assert llm["play_agent_model_provider"] == "openai"
    assert llm["play_agent_monkey_mode"] is False
    assert llm["preferred_provider"] == "openai"
    assert llm["ollama_url"] == "http://localhost:11434"


async def test_save_llm_settings_persists_play_agent_model(client: AsyncClient):
    """Play agent should support dedicated model/provider configuration."""
    payload = {
        "small_model": "gpt-4o-mini",
        "small_model_provider": "openai",
        "complex_model": "gpt-4o",
        "complex_model_provider": "openai",
        "generator_model": "gpt-4o",
        "generator_model_provider": "openai",
        "play_agent_model": "gpt-5.3",
        "play_agent_model_provider": "openai",
        "play_agent_monkey_mode": True,
        "play_agent_personality": "Bürokrat",
        "play_agent_custom_personality": "Ensure all documents are signed.",
        "preferred_provider": "openai",
        "ollama_url": "http://localhost:11434",
    }

    save_resp = await client.post("/api/settings/llm", json=payload)
    assert save_resp.status_code == 200

    settings_resp = await client.get("/api/settings")
    assert settings_resp.status_code == 200
    llm = settings_resp.json()["llm_settings"]
    assert llm["play_agent_model"] == "gpt-5.3"
    assert llm["play_agent_model_provider"] == "openai"
    assert llm["play_agent_monkey_mode"] is True
    assert llm["play_agent_personality"] == "bureaucrat"
    assert llm["play_agent_custom_personality"] == "Ensure all documents are signed."


async def test_get_settings_uses_installed_ollama_models(client: AsyncClient, monkeypatch):
    """Settings constants should expose installed Ollama models for LLM selection."""

    llm_payload = {
        "small_model": "llama3.2",
        "small_model_provider": "ollama",
        "small_max_tokens": 2048,
        "small_enable_thinking": False,
        "small_max_thinking_tokens": 1024,
        "complex_model": "qwen2.5",
        "complex_model_provider": "ollama",
        "complex_max_tokens": 4096,
        "complex_enable_thinking": False,
        "complex_max_thinking_tokens": 1024,
        "generator_model": "qwen2.5",
        "generator_model_provider": "ollama",
        "generator_max_tokens": 4096,
        "generator_enable_thinking": False,
        "generator_max_thinking_tokens": 1024,
        "play_agent_model": "llama3.2",
        "play_agent_model_provider": "ollama",
        "preferred_provider": "ollama",
        "ollama_url": "http://localhost:11434",
    }
    save_resp = await client.post("/api/settings/llm", json=llm_payload)
    assert save_resp.status_code == 200

    async def fake_fetch_models(_ollama_url: Optional[str]):
        return ["llama3.2:latest", "qwen2.5:14b"]

    monkeypatch.setattr(config_api, "_fetch_ollama_models", fake_fetch_models)

    resp = await client.get("/api/settings")
    assert resp.status_code == 200
    models = resp.json()["available_constants"]["predefined_llm_models"]["ollama"]
    assert models == ["llama3.2:latest", "qwen2.5:14b"]


async def test_get_settings_does_not_fetch_ollama_models_when_not_configured(
    client: AsyncClient, monkeypatch
):
    """Settings constants should not query Ollama when no LLM provider uses Ollama."""

    llm_payload = {
        "small_model": "gpt-5.4-mini",
        "small_model_provider": "openai",
        "small_max_tokens": 2048,
        "small_enable_thinking": False,
        "small_max_thinking_tokens": 1024,
        "complex_model": "gpt-5.4-mini",
        "complex_model_provider": "openai",
        "complex_max_tokens": 4096,
        "complex_enable_thinking": False,
        "complex_max_thinking_tokens": 1024,
        "generator_model": "gpt-5.4-mini",
        "generator_model_provider": "openai",
        "generator_max_tokens": 4096,
        "generator_enable_thinking": False,
        "generator_max_thinking_tokens": 1024,
        "play_agent_model": "gpt-5.4-mini",
        "play_agent_model_provider": "openai",
        "preferred_provider": "openai",
        "ollama_url": "http://localhost:11434",
    }
    save_resp = await client.post("/api/settings/llm", json=llm_payload)
    assert save_resp.status_code == 200

    async def fail_if_called(_ollama_url: Optional[str]):
        raise AssertionError("_fetch_ollama_models should not be called")

    monkeypatch.setattr(config_api, "_fetch_ollama_models", fail_if_called)

    resp = await client.get("/api/settings")
    assert resp.status_code == 200
    models = resp.json()["available_constants"]["predefined_llm_models"]["ollama"]
    assert models == config_api.PREDEFINED_LLM_MODELS["ollama"]


async def test_get_ollama_models_endpoint(client: AsyncClient, monkeypatch):
    """Dedicated Ollama models endpoint should return detected local models."""

    async def fake_fetch_models(_ollama_url: Optional[str]):
        return ["mistral:latest"]

    monkeypatch.setattr(config_api, "_fetch_ollama_models", fake_fetch_models)

    resp = await client.get("/api/settings/ollama-models?ollama_url=http://localhost:11434")
    assert resp.status_code == 200
    assert resp.json() == {"models": ["mistral:latest"]}


async def test_get_settings_returns_style_and_tone_catalogs(client: AsyncClient):
    """Default settings should include selectable image styles and tones."""
    resp = await client.get("/api/settings")
    assert resp.status_code == 200
    payload = resp.json()
    assert isinstance(payload["image_styles_catalog"], list)
    assert len(payload["image_styles_catalog"]) > 0
    assert isinstance(payload["tone_catalog"], list)
    assert len(payload["tone_catalog"]) > 0


async def test_save_image_styles_catalog(client: AsyncClient):
    """Admin can persist a custom image style catalog payload."""
    catalog = [
        {
            "id": "chalk-noir",
            "name": "Chalk Noir",
            "description": "Monochrome chalk and smoke.",
            "instruction": "chalk texture, noir composition",
            "image_url": None,
        }
    ]

    save_resp = await client.post("/api/settings/image-styles", json={"items": catalog})
    assert save_resp.status_code == 200
    assert save_resp.json()["status"] == "success"

    settings_resp = await client.get("/api/settings")
    assert settings_resp.status_code == 200
    payload = settings_resp.json()
    assert payload["image_styles_catalog"][0]["id"] == "chalk-noir"


async def test_save_tone_catalog(client: AsyncClient):
    """Admin can persist a custom world tone catalog payload."""
    catalog = [
        {
            "id": "satire",
            "name": "Satire",
            "description": "Playful critique with sharp humor.",
            "instruction": "Keep satirical framing with witty contrast.",
            "image_url": None,
        }
    ]

    save_resp = await client.post("/api/settings/tones", json={"items": catalog})
    assert save_resp.status_code == 200
    assert save_resp.json()["status"] == "success"

    settings_resp = await client.get("/api/settings")
    assert settings_resp.status_code == 200
    payload = settings_resp.json()
    assert payload["tone_catalog"][0]["id"] == "satire"


async def test_settings_are_global_for_all_users(client: AsyncClient):
    """Updating settings as one admin user should apply to all users globally."""
    user_a = "settings_user_a"
    user_b = "settings_user_b"

    async with TestSessionLocal() as session:
        session.add(User(username=user_a, hashed_password=get_password_hash("pw-a"), role="admin"))
        session.add(User(username=user_b, hashed_password=get_password_hash("pw-b"), role="admin"))
        await session.commit()

    headers_a = {"Authorization": f"Bearer {create_access_token({'sub': user_a})}"}
    headers_b = {"Authorization": f"Bearer {create_access_token({'sub': user_b})}"}

    payload_a = {
        "small_model": "llama3.2",
        "small_model_provider": "ollama",
        "small_max_tokens": 1024,
        "small_enable_thinking": False,
        "small_max_thinking_tokens": 256,
        "complex_model": "qwen2.5",
        "complex_model_provider": "ollama",
        "generator_model_provider": "ollama",
        "complex_max_tokens": 4096,
        "complex_enable_thinking": False,
        "complex_max_thinking_tokens": 512,
        "generator_model": "llama3.2",
        "preferred_provider": "ollama",
        "ollama_url": "http://localhost:11434",
    }

    for index, role in enumerate(("small", "complex", "generator", "compression", "play_agent"), 1):
        payload_a.update(
            {
                f"{role}_ollama_url": f"http://127.0.0.1:{11440 + index}",
                f"{role}_ollama_timeout": 100 + index,
                f"{role}_ollama_num_ctx": 4096 * index,
            }
        )
    save_resp = await client.post("/api/settings/llm", json=payload_a, headers=headers_a)
    assert save_resp.status_code == 200

    a_settings = await client.get("/api/settings", headers=headers_a)
    assert a_settings.status_code == 200
    assert a_settings.json()["llm_settings"]["small_model"] == "llama3.2"

    b_settings = await client.get("/api/settings", headers=headers_b)
    assert b_settings.status_code == 200
    assert b_settings.json()["llm_settings"]["small_model"] == "llama3.2"
    for role in ("small", "complex", "generator", "compression", "play_agent"):
        for option in ("url", "timeout", "num_ctx"):
            key = f"{role}_ollama_{option}"
            assert b_settings.json()["llm_settings"][key] == payload_a[key]


async def test_test_llm_connection_handles_authentication_errors_gracefully(
    client: AsyncClient, monkeypatch
):
    """/test-llm must return a user-safe error response for provider auth failures."""

    class _FakeLLM:
        def __init__(self, *args, **kwargs):
            pass

        async def aexecute_simple_task(self, **kwargs):
            raise Exception("litellm.AuthenticationError: Invalid Authentication")

    monkeypatch.setattr(config_api, "GameMasterLLM", RoleLLMFactory(_FakeLLM))

    resp = await client.post(
        "/api/settings/test-llm",
        json={
            "provider": "kimi",
            "model": "moonshot-v1-8k",
        },
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "error"
    assert "Authentication failed" in data["message"]


async def test_test_llm_connection_handles_generic_errors_without_500(
    client: AsyncClient, monkeypatch
):
    """Generic runtime errors from LLM test endpoint should not bubble up as HTTP 500."""

    class _FakeLLM:
        def __init__(self, *args, **kwargs):
            pass

        async def aexecute_simple_task(self, **kwargs):
            raise RuntimeError("upstream timeout")

    monkeypatch.setattr(config_api, "GameMasterLLM", RoleLLMFactory(_FakeLLM))

    resp = await client.post(
        "/api/settings/test-llm",
        json={
            "provider": "openai",
            "model": "gpt-5.3",
        },
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "error"
    assert "Connection test failed" in data["message"]


async def test_ollama_role_settings_round_trip_and_legacy_defaults(client, monkeypatch):
    from backend.core.config import settings

    monkeypatch.setattr(settings, "ALLOW_PRIVATE_NETWORK_MODELS", True)
    monkeypatch.setattr(
        settings,
        "__pydantic_fields_set__",
        settings.model_fields_set | {"ALLOW_PRIVATE_NETWORK_MODELS"},
    )
    payload = (await client.get("/api/settings")).json()["llm_settings"]
    assert payload["small_ollama_url"] == ""
    assert payload["complex_ollama_timeout"] is None
    payload.update(
        small_ollama_url=" http://127.0.0.1:11435/ ",
        small_ollama_timeout=60,
        small_ollama_num_ctx=8192,
        complex_ollama_url="http://127.0.0.1:11436",
        complex_ollama_timeout=150,
        complex_ollama_num_ctx=32768,
        play_agent_model_provider="ollama",
        play_agent_model="qwen:latest",
        play_agent_personality="Bürokrat",
        play_agent_custom_personality="Check every inventory transfer.",
        custom_openai_url="http://127.0.0.1:8002/v1",
        custom_openai_timeout=120,
        custom_openai_response_format="json_schema",
    )
    for index, role in enumerate(("generator", "compression", "play_agent"), 1):
        payload.update(
            {
                f"{role}_ollama_url": f"http://127.0.0.1:{11440 + index}/",
                f"{role}_ollama_timeout": 100 + index,
                f"{role}_ollama_num_ctx": 4096 * index,
            }
        )
    payload["ollama_api_mode"] = "chat"
    result = await client.post("/api/settings/llm", json=payload)
    assert result.status_code == 200
    saved = (await client.get("/api/settings")).json()["llm_settings"]
    assert saved["ollama_api_mode"] == "chat"
    assert saved["play_agent_personality"] == "bureaucrat"
    assert saved["play_agent_custom_personality"] == payload["play_agent_custom_personality"]
    assert saved["play_agent_model_provider"] == "ollama"
    assert saved["play_agent_model"] == "qwen:latest"
    for key in ("custom_openai_url", "custom_openai_timeout", "custom_openai_response_format"):
        assert saved[key] == payload[key]
    for role in ("small", "complex", "generator", "compression", "play_agent"):
        for option in ("url", "timeout", "num_ctx"):
            key = f"{role}_ollama_{option}"
            assert saved[key] == (
                payload[key].strip().rstrip("/") if option == "url" else payload[key]
            )


@pytest.mark.parametrize("empty", ["", "   ", None])
async def test_empty_ollama_role_numbers_are_unset(client, empty):
    payload = (await client.get("/api/settings")).json()["llm_settings"]
    for role in ("small", "complex", "generator", "compression", "play_agent"):
        payload[f"{role}_ollama_timeout"] = empty
        payload[f"{role}_ollama_num_ctx"] = empty
    assert (await client.post("/api/settings/llm", json=payload)).status_code == 200
    saved = (await client.get("/api/settings")).json()["llm_settings"]
    assert all(
        saved[f"{role}_ollama_{option}"] is None
        for role in ("small", "complex", "generator", "compression", "play_agent")
        for option in ("timeout", "num_ctx")
    )


@pytest.mark.parametrize(
    ("option", "invalid"),
    [("timeout", 29), ("timeout", 601), ("num_ctx", 511), ("num_ctx", 1048577)],
)
@pytest.mark.parametrize("role", ["small", "complex", "generator", "compression", "play_agent"])
async def test_invalid_ollama_role_numbers_are_rejected(client, option, invalid, role):
    payload = (await client.get("/api/settings")).json()["llm_settings"]
    payload[f"{role}_ollama_{option}"] = invalid
    assert (await client.post("/api/settings/llm", json=payload)).status_code == 422


@pytest.mark.parametrize("role", ["small", "complex", "generator", "compression", "play_agent"])
async def test_unsafe_ollama_role_url_rejected(client, monkeypatch, role):
    from backend.core.config import settings

    monkeypatch.setattr(settings, "ALLOW_PRIVATE_NETWORK_MODELS", False)
    payload = (await client.get("/api/settings")).json()["llm_settings"]
    payload[f"{role}_ollama_url"] = "http://169.254.169.254/latest/meta-data"
    response = await client.post("/api/settings/llm", json=payload)
    assert response.status_code == 400
    assert "private/loopback" in response.json()["detail"]


@pytest.mark.parametrize("role", ["small", "complex", "generator", "compression", "play_agent"])
async def test_llm_test_uses_selected_ollama_role_without_persisting(client, monkeypatch, role):
    before = (await client.get("/api/settings")).json()["llm_settings"]
    captured = {}

    class FakeLLM:
        def __init__(self, user, provider, model_category):
            captured.update(
                provider=provider, category=model_category, settings=dict(user.llm_settings)
            )

        async def aexecute_simple_task(self, **kwargs):
            return "connected"

    monkeypatch.setattr(config_api, "GameMasterLLM", RoleLLMFactory(FakeLLM))
    response = await client.post(
        "/api/settings/test-llm",
        json={
            "provider": "ollama",
            "ollama_api_mode": "chat",
            "model": "role-model:latest",
            "role": role,
            "ollama_url": "http://127.0.0.1:11439/",
            "ollama_timeout": 60,
            "ollama_num_ctx": 8192,
        },
    )
    assert response.json()["status"] == "success"
    assert captured["category"] == role
    assert captured["settings"]["ollama_api_mode"] == "chat"
    assert captured["settings"][f"{role}_ollama_url"] == "http://127.0.0.1:11439"
    assert captured["settings"][f"{role}_ollama_timeout"] == 60
    assert captured["settings"][f"{role}_ollama_num_ctx"] == 8192
    after = (await client.get("/api/settings")).json()["llm_settings"]
    assert after == before


@pytest.mark.parametrize("role", ["small", "complex", "generator", "compression", "play_agent"])
async def test_ollama_connection_rejects_unsafe_url(client, monkeypatch, role):
    from backend.core.config import settings

    monkeypatch.setattr(settings, "ALLOW_PRIVATE_NETWORK_MODELS", False)
    before = (await client.get("/api/settings")).json()["llm_settings"]
    response = await client.post(
        "/api/settings/test-llm",
        json={
            "provider": "ollama",
            "model": "local",
            "role": role,
            "ollama_url": "http://169.254.169.254/",
        },
    )
    assert response.status_code == 400
    assert (await client.get("/api/settings")).json()["llm_settings"] == before


@pytest.mark.parametrize("role", ["small", "complex", "generator", "compression", "play_agent"])
async def test_explicit_ollama_role_without_model_is_not_replaced(client, role):
    payload = (await client.get("/api/settings")).json()["llm_settings"]
    payload.update(
        small_model="gpt-4o-mini",
        small_model_provider="openai",
        complex_model="gpt-4o",
        complex_model_provider="openai",
    )
    payload[f"{role}_model_provider"] = "ollama"
    payload[f"{role}_model"] = ""
    assert (await client.post("/api/settings/llm", json=payload)).status_code == 200
    saved = (await client.get("/api/settings")).json()["llm_settings"]
    assert saved[f"{role}_model_provider"] == "ollama"
    assert saved[f"{role}_model"] == ""


async def test_invalid_ollama_api_mode_is_rejected(client):
    payload = (await client.get("/api/settings")).json()["llm_settings"]
    payload["ollama_api_mode"] = "unknown"
    assert (await client.post("/api/settings/llm", json=payload)).status_code == 422
