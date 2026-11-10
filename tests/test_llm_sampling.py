"""Sampling stays opt-in, role-local, validated, and correctly mapped on the wire."""

from copy import deepcopy
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from backend.core.llm_roles import LLM_ROLES
from backend.core.llm_router import GameMasterLLM
from backend.core.llm_sampling import SamplingProfile, SamplingSettings, apply, resolve
from backend.models.user import User
from tests.test_custom_openai import local_policy
from tests.test_custom_openai_roles import preferences

__all__ = ["local_policy"]


@pytest.mark.parametrize("provider", ["ollama", "custom_openai", "openai", "anthropic"])
def test_empty_profile_preserves_existing_request(provider):
    options = {"max_tokens": 4000, "num_ctx": 8192}
    original = deepcopy(options)
    apply(options, resolve({}, "complex"), provider)
    assert options == original


@pytest.mark.parametrize(
    "field,value",
    [
        ("temperature", -0.1),
        ("temperature", 2.1),
        ("temperature", True),
        ("temperature", float("nan")),
        ("top_p", 0),
        ("top_p", 1.1),
        ("top_k", 2.5),
        ("top_k", -1),
        ("min_p", float("inf")),
        ("min_p", -0.1),
        ("repetition_penalty", 0),
        ("repetition_penalty", 2.1),
    ],
)
def test_invalid_values_are_rejected_before_inference(field, value):
    with pytest.raises(ValidationError):
        SamplingProfile.model_validate({field: value})


def test_zero_and_blank_numbers_keep_distinct_meanings():
    profile = SamplingProfile(temperature=0, top_k=0, min_p=0)
    assert profile.temperature == profile.top_k == profile.min_p == 0
    assert SamplingProfile.model_validate({"temperature": ""}).temperature is None
    assert SamplingProfile.model_validate_json(profile.model_dump_json()) == profile


def test_role_profiles_are_independent_and_disabled_values_survive():
    data = {
        "sampling": {
            "defaults": {"temperature": 0.7},
            "roles": {
                "complex": {"enabled": True, "profile": {"temperature": 1.05}},
                "small": {"enabled": True, "profile": {"temperature": 0.15}},
                "generator": {"enabled": False, "profile": {"temperature": 1.2}},
            },
        }
    }
    original = deepcopy(data)
    assert resolve(data, "complex").temperature == 1.05
    assert resolve(data, "small").temperature == 0.15
    assert resolve(data, "generator").temperature == 0.7
    assert resolve(data, "compression").temperature == 0.7
    assert resolve(data, None).temperature == 0.7
    assert data == original
    data["sampling"]["roles"]["small"]["profile"] = {}
    assert resolve(data, "small").temperature is None


def test_local_extensions_are_explicit_and_never_leak_to_cloud():
    profile = SamplingProfile(
        temperature=0.8, top_p=0.95, top_k=50, min_p=0.05, repetition_penalty=1.05
    )
    for provider in ("openai", "anthropic", "google", "custom_openai"):
        options = {}
        apply(options, profile, provider)
        assert options == {"temperature": 0.8, "top_p": 0.95}
    ollama = {}
    apply(ollama, profile, "ollama")
    assert ollama["repeat_penalty"] == 1.05 and "repetition_penalty" not in ollama
    custom = {"extra_body": {"existing": "kept"}}
    apply(custom, profile.model_copy(update={"local_extensions": True}), "custom_openai")
    assert custom["extra_body"] == {
        "existing": "kept",
        "top_k": 50,
        "min_p": 0.05,
        "repetition_penalty": 1.05,
    }


@pytest.mark.parametrize("role", LLM_ROLES)
async def test_every_role_uses_its_sampling_on_generation(monkeypatch, role):
    cfg = {
        f"{role}_model_provider": "ollama",
        f"{role}_model": "local",
        "sampling": {
            "defaults": {"temperature": 0.7},
            "roles": {role: {"enabled": True, "profile": {"temperature": 0.25}}},
        },
    }
    calls = []

    async def complete(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))], model_dump=lambda: {}
        )

    monkeypatch.setattr("backend.core.llm_router.litellm.acompletion", complete)
    router = GameMasterLLM.for_role(User(llm_settings=cfg), role)
    await router.aexecute_simple_task("system", "input", router.model)
    assert calls[0]["temperature"] == 0.25


async def test_settings_save_reload_clear_and_invalid_update_are_atomic(auth_client, local_policy):
    old = (await auth_client.get("/api/settings")).json()["llm_settings"]
    sampling = SamplingSettings.model_validate(
        {
            "defaults": {"temperature": 0.7},
            "roles": {
                "complex": {
                    "enabled": True,
                    "profile": {"temperature": 1.05, "top_k": 60, "local_extensions": True},
                },
                "small": {"enabled": True, "profile": {"temperature": 0.15}},
            },
        }
    ).model_dump()
    response = await auth_client.post(
        "/api/settings/llm", json={**old, **preferences(), "sampling": sampling}
    )
    assert response.status_code == 200, response.text
    saved = (await auth_client.get("/api/settings")).json()["llm_settings"]
    assert saved["sampling"] == sampling
    invalid = deepcopy(sampling)
    invalid["roles"]["small"]["profile"]["top_k"] = 1.5
    assert (
        await auth_client.post("/api/settings/llm", json={**saved, "sampling": invalid})
    ).status_code == 422
    assert (await auth_client.get("/api/settings")).json()["llm_settings"] == saved
    sampling["roles"]["complex"]["profile"]["temperature"] = None
    assert (
        await auth_client.post("/api/settings/llm", json={**saved, "sampling": sampling})
    ).status_code == 200
    restored = (await auth_client.get("/api/settings")).json()["llm_settings"]
    assert resolve(restored, "complex").temperature is None
    assert resolve(restored, "small").temperature == 0.15


async def test_connection_test_uses_unsaved_role_sampling_without_saving(
    auth_client, local_policy, monkeypatch
):
    old = (await auth_client.get("/api/settings")).json()["llm_settings"]
    calls = []

    async def test(router, model):
        calls.append(router.sampling)
        return "ok"

    monkeypatch.setattr("backend.core.llm_connection_test.test_connection", test)
    response = await auth_client.post(
        "/api/settings/test-llm",
        json={
            "provider": "custom_openai",
            "model": "local",
            "role": "complex",
            "custom_openai_url": "http://127.0.0.1:8080/v1",
            "sampling": {"temperature": 1.1},
        },
    )
    assert response.json()["status"] == "success", response.text
    assert calls[0].temperature == 1.1
    assert (await auth_client.get("/api/settings")).json()["llm_settings"] == old
