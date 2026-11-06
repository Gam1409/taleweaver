"""Shared endpoints and role overrides agree across persistence, tests and routing."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.api.routes import config_api
from backend.core import custom_openai
from backend.core.custom_openai_roles import resolve_url
from backend.core.llm_roles import LLM_ROLES
from backend.core.llm_router import GameMasterLLM
from backend.models.user import User
from tests.test_custom_openai import local_policy

__all__ = ["local_policy"]
GLOBAL = "http://127.0.0.1:8080/v1"


def preferences():
    return {
        "custom_openai_url": GLOBAL,
        **{f"{role}_model_provider": "custom_openai" for role in LLM_ROLES},
        **{f"{role}_model": f"model-{role}" for role in LLM_ROLES},
    }


@pytest.mark.parametrize("role", LLM_ROLES)
def test_each_role_routes_to_its_own_url_and_blank_inherits(role):
    prefs = preferences()
    alternate = "http://127.0.0.1:9090/v1"
    prefs[f"{role}_custom_openai_url"] = alternate
    user = User(username="roles", llm_settings=prefs, encrypted_api_keys={})
    assert GameMasterLLM.for_role(user, role).api_base == alternate
    assert (
        GameMasterLLM(
            user, provider="custom_openai", model_category=role, use_role_settings=False
        ).api_base
        == GLOBAL
    )
    for other in set(LLM_ROLES) - {role}:
        assert GameMasterLLM.for_role(user, other).api_base == GLOBAL
    user.llm_settings = {**prefs, f"{role}_custom_openai_url": "   "}
    assert GameMasterLLM.for_role(user, role).api_base == GLOBAL


async def test_save_reload_and_runtime_keep_all_role_urls(auth_client, local_policy):
    old = (await auth_client.get("/api/settings")).json()["llm_settings"]
    urls = {
        f"{role}_custom_openai_url": f"http://127.0.0.1:{8100 + index}/v1"
        for index, role in enumerate(LLM_ROLES)
    }
    response = await auth_client.post("/api/settings/llm", json={**old, **preferences(), **urls})
    assert response.status_code == 200, response.text
    restored = (await auth_client.get("/api/settings")).json()["llm_settings"]
    assert all(restored[key] == url for key, url in urls.items())
    user = User(username="restored", llm_settings=restored, encrypted_api_keys={})
    assert all(
        GameMasterLLM.for_role(user, role).api_base == urls[f"{role}_custom_openai_url"]
        for role in LLM_ROLES
    )


@pytest.mark.parametrize("role", LLM_ROLES)
async def test_metadata_urls_are_rejected_even_in_an_inactive_role(auth_client, local_policy, role):
    original = (await auth_client.get("/api/settings")).json()["llm_settings"]
    response = await auth_client.post(
        "/api/settings/llm",
        json={**original, f"{role}_custom_openai_url": "http://169.254.169.254/v1"},
    )
    assert response.status_code == 400, response.text
    assert (await auth_client.get("/api/settings")).json()["llm_settings"] == original


async def test_unsaved_connection_test_uses_selected_role_url_without_persisting(
    auth_client, local_policy, monkeypatch
):
    original = (await auth_client.get("/api/settings")).json()["llm_settings"]
    calls = []

    async def test(router, model):
        calls.append((router.model_category, router.api_base, model))
        return "ok"

    monkeypatch.setattr(custom_openai, "test_connection", test)
    response = await auth_client.post(
        "/api/settings/test-llm",
        json={
            "provider": "custom_openai",
            "model": "unsaved-model",
            "role": "compression",
            "custom_openai_url": GLOBAL,
        },
    )
    assert response.status_code == 200 and response.json()["status"] == "success", response.text
    assert calls == [("compression", GLOBAL, "unsaved-model")]
    assert (await auth_client.get("/api/settings")).json()["llm_settings"] == original


async def test_discovery_uses_the_same_explicit_endpoint(auth_client, monkeypatch):
    discover = AsyncMock(return_value=["local-model"])
    monkeypatch.setattr(custom_openai, "discover_models", discover)
    response = await auth_client.get(
        "/api/settings/llm-models", params={"provider": "custom_openai", "api_base": GLOBAL}
    )
    assert response.status_code == 200, response.text
    assert discover.call_args.args[0] == GLOBAL


def test_role_only_endpoints_are_configured_without_a_global_url():
    prefs = {
        **preferences(),
        "custom_openai_url": "",
        "small_custom_openai_url": GLOBAL,
        "complex_custom_openai_url": GLOBAL,
    }
    assert config_api._is_llm_configured(SimpleNamespace(llm_settings=prefs), {})
    assert resolve_url(prefs, "small") == GLOBAL


def test_url_overrides_do_not_replace_another_provider():
    user = User(
        username="mixed",
        encrypted_api_keys={},
        llm_settings={
            **preferences(),
            "small_model_provider": "ollama",
            "small_model": "local",
            "small_custom_openai_url": "http://127.0.0.1:9999/v1",
            "ollama_url": "http://localhost:11434",
        },
    )
    router = GameMasterLLM.for_role(user, "small")
    assert router.provider == "ollama" and router.api_base == "http://localhost:11434"
