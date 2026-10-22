"""Role resolution, inheritance and independent Ollama request settings."""

from itertools import combinations
from types import SimpleNamespace

import pytest

from backend.core.config import settings
from backend.core.llm_roles import LLM_ROLES, resolve_llm_role
from backend.core.llm_router import GameMasterLLM
from backend.models.user import User


@pytest.mark.parametrize("role", LLM_ROLES)
@pytest.mark.parametrize(
    "url,global_url,expected",
    [
        (" http://role:11434/ ", "http://global:11434", "http://role:11434"),
        ("", "http://global:11434/", "http://global:11434"),
        (None, "  ", "http://localhost:11434"),
    ],
)
def test_role_url_and_default_timeout(role, url, global_url, expected):
    user = User(
        llm_settings={
            f"{role}_model_provider": "ollama",
            f"{role}_model": "local:latest",
            f"{role}_ollama_url": url,
            "ollama_url": global_url,
        }
    )
    router = GameMasterLLM.for_role(user, role)
    assert router.api_base == expected
    assert router.request_timeout == (
        settings.WORLDBUILDING_TIMEOUT if role == "generator" else settings.INTELLIGENCE_TIMEOUT
    )
    assert router.ollama_num_ctx is None


@pytest.mark.parametrize("roles", list(combinations(LLM_ROLES, 2)))
@pytest.mark.parametrize("shared_url", [False, True])
@pytest.mark.asyncio
async def test_role_pairs_send_independent_requests(monkeypatch, roles, shared_url):
    cfg = {}
    calls = []

    async def complete(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))], model_dump=lambda: {}
        )

    monkeypatch.setattr("backend.core.llm_router.litellm.acompletion", complete)
    for index, role in enumerate(roles, 1):
        cfg.update(
            {
                f"{role}_model_provider": "ollama",
                f"{role}_model": f"model-{index}",
                f"{role}_ollama_url": f"http://host-{1 if shared_url else index}:11434",
                f"{role}_ollama_timeout": index * 90,
                f"{role}_ollama_num_ctx": index * 8192,
            }
        )
    user = User(llm_settings=cfg)
    for role in roles:
        router = GameMasterLLM.for_role(user, role)
        await router.aexecute_simple_task("sys", "hello", router.model)
    for index, call in enumerate(calls, 1):
        assert call["api_base"] == f"http://host-{1 if shared_url else index}:11434"
        assert call["model"] == f"model-{index}"
        assert call["request_timeout"] == index * 90
        assert call["num_ctx"] == index * 8192
        assert call["max_tokens"] > 0
        assert "extra_body" not in call


@pytest.mark.parametrize("role", LLM_ROLES)
def test_empty_ollama_model_is_configuration_error(role):
    with pytest.raises(ValueError, match=f"No model configured for role '{role}'"):
        resolve_llm_role({f"{role}_model_provider": "ollama", f"{role}_model": " "}, role)


@pytest.mark.parametrize(
    "role,default",
    [
        ("small", "gpt-4o-mini"),
        ("complex", "gpt-4o"),
        ("generator", "gpt-4o"),
        ("compression", "gpt-4o-mini"),
        ("play_agent", "gpt-4o-mini"),
    ],
)
def test_cloud_default_models(role, default):
    config = resolve_llm_role({}, role)
    assert (config.provider, config.model) == ("openai", default)


@pytest.mark.parametrize(
    "role,donor",
    [
        ("small", "complex"),
        ("complex", "small"),
        ("generator", "complex"),
        ("compression", "small"),
        ("play_agent", "small"),
    ],
)
def test_provider_and_model_inherit_as_a_pair(role, donor):
    config = resolve_llm_role(
        {
            f"{role}_model": "stale-other-provider-model",
            f"{donor}_model_provider": "anthropic",
            f"{donor}_model": "claude-test",
        },
        role,
    )
    assert (config.provider, config.model, config.source_role) == (
        "anthropic",
        "claude-test",
        donor,
    )


@pytest.mark.parametrize("role", LLM_ROLES)
def test_cloud_role_ignores_ollama_overrides(monkeypatch, role):
    monkeypatch.setattr(GameMasterLLM, "_get_decrypted_key", lambda self, provider: "fake")
    user = User(
        llm_settings={
            f"{role}_model_provider": "openai",
            f"{role}_ollama_url": "http://ignored",
            f"{role}_ollama_timeout": 400,
            f"{role}_ollama_num_ctx": 32768,
        }
    )
    router = GameMasterLLM.for_role(user, role)
    assert router.api_base is None
    assert router.ollama_num_ctx is None
    assert router.request_timeout == (
        settings.WORLDBUILDING_TIMEOUT if role == "generator" else settings.INTELLIGENCE_TIMEOUT
    )


def test_play_agent_has_own_endpoint_and_legacy_small_token_settings():
    router = GameMasterLLM.for_role(
        User(
            llm_settings={
                "play_agent_model_provider": "ollama",
                "play_agent_model": "agent",
                "play_agent_ollama_url": "http://agent:11434",
                "small_model_provider": "openai",
                "small_ollama_url": "http://wrong",
                "small_max_tokens": 777,
                "enable_thinking": True,
            }
        ),
        "play_agent",
    )
    assert router.api_base == "http://agent:11434"
    assert router.max_tokens == 777
    assert router.enable_thinking is False
    assert router.model_category == "play_agent"


def test_turn_context_reports_missing_ollama_model():
    from backend.api.routes.adventures.turn_context_helpers import resolve_model_settings

    with pytest.raises(ValueError, match="role 'small'"):
        resolve_model_settings({"small_model_provider": "ollama"})


@pytest.mark.asyncio
async def test_editor_fallback_keeps_each_candidate_role(monkeypatch):
    from backend.api.routes.adventures.editing import ai_fix_llm

    user = User(
        llm_settings={
            "complex_model_provider": "ollama",
            "complex_model": "shared-model",
            "complex_ollama_url": "http://complex:11434",
            "small_model_provider": "ollama",
            "small_model": "shared-model",
            "small_ollama_url": "http://small:11434",
        }
    )
    calls = []

    async def call(gm, **kwargs):
        calls.append((gm.model_category, gm.api_base, kwargs["model"]))
        if gm.model_category == "complex":
            raise ValueError("Try the other server")
        return "success"

    monkeypatch.setattr(ai_fix_llm, "_call_provider", call)
    result, provider = await ai_fix_llm._generate_llm_proposals(
        user_prompt="hello",
        current_user=user,
        response_model=dict,
        gm_kwargs={},
        allow_fallback=False,
    )
    assert result == "success"
    assert provider == "ollama"
    assert calls == [
        ("complex", "http://complex:11434", "shared-model"),
        ("small", "http://small:11434", "shared-model"),
    ]


def test_environment_fallback_does_not_inherit_complex_ollama_settings():
    router = GameMasterLLM(
        User(
            llm_settings={
                "complex_model_provider": "ollama",
                "complex_ollama_url": "http://wrong",
                "complex_ollama_timeout": 400,
                "complex_ollama_num_ctx": 32768,
                "ollama_url": "http://global:11434",
            }
        ),
        provider="ollama",
        model_category="complex",
        use_role_settings=False,
    )
    assert router.api_base == "http://global:11434"
    assert router.ollama_num_ctx is None
    assert router.request_timeout == settings.INTELLIGENCE_TIMEOUT


@pytest.mark.parametrize("role", LLM_ROLES)
@pytest.mark.parametrize("enabled", [False, True])
def test_ollama_sends_configured_thinking_flag(role, enabled):
    prefix = "small" if role == "play_agent" else role
    router = GameMasterLLM.for_role(
        User(
            llm_settings={
                f"{role}_model_provider": "ollama",
                f"{role}_model": "local-test",
                f"{prefix}_enable_thinking": enabled,
            }
        ),
        role,
    )
    kwargs = {}
    router._apply_ollama_options(kwargs, router.model)
    assert kwargs["think"] is enabled


@pytest.mark.parametrize("api_mode,provider", [("generate", "ollama"), ("chat", "ollama_chat")])
def test_saved_ollama_api_mode_selects_litellm_transport(api_mode, provider):
    router = GameMasterLLM.for_role(
        User(
            llm_settings={
                "small_model_provider": "ollama",
                "small_model": "local-test",
                "ollama_api_mode": api_mode,
            }
        ),
        "small",
    )
    kwargs = {}
    router._apply_ollama_options(kwargs, router.model)
    assert kwargs["custom_llm_provider"] == provider
