"""Tests for strict provider routing behavior in GameMasterLLM."""

import pytest
from pydantic import BaseModel

from backend.core.llm_router import GameMasterLLM
from backend.models.user import User


def _make_user(llm_settings=None, encrypted_api_keys=None):
    return User(
        username="tester",
        llm_settings=llm_settings or {},
        encrypted_api_keys=encrypted_api_keys or {},
    )


def test_ollama_rejects_cloud_prefixed_model():
    user = _make_user(llm_settings={"ollama_url": "http://localhost:11434"})
    router = GameMasterLLM(user, provider="ollama")

    with pytest.raises(ValueError, match="Provider is 'ollama' but model"):
        router.execute_simple_task(
            system_prompt="sys",
            user_prompt="hello",
            model="openai/gpt-4o-mini",
        )


def test_ollama_simple_task_uses_local_base_without_api_key(monkeypatch):
    user = _make_user(llm_settings={"ollama_url": "http://localhost:11434"})
    router = GameMasterLLM(user, provider="ollama")

    captured = {}

    class _Msg:
        content = "ok"

    class _Choice:
        message = _Msg()

    class _Resp:
        choices = [_Choice()]

        @staticmethod
        def model_dump():
            return {}

    def fake_completion(**kwargs):
        captured.update(kwargs)
        return _Resp()

    monkeypatch.setattr("backend.core.llm_router.litellm.completion", fake_completion)

    out = router.execute_simple_task(
        system_prompt="sys",
        user_prompt="hello",
        model="llama3.2",
    )

    assert out == "ok"
    assert captured["custom_llm_provider"] == "ollama"
    assert captured["api_base"] == "http://localhost:11434"
    assert "api_key" not in captured


def test_openrouter_normalizes_prefixed_model(monkeypatch):
    user = _make_user(
        llm_settings={"ollama_url": "http://localhost:11434"},
        encrypted_api_keys={"openrouter": "encrypted-placeholder"},
    )

    monkeypatch.setattr(
        "backend.core.llm_router.GameMasterLLM._get_decrypted_key",
        lambda self, provider: "sk-or-v1-test",
    )

    router = GameMasterLLM(user, provider="openrouter")

    captured = {}

    class _Msg:
        content = "ok"

    class _Choice:
        message = _Msg()

    class _Resp:
        choices = [_Choice()]

        @staticmethod
        def model_dump():
            return {}

    def fake_completion(**kwargs):
        captured.update(kwargs)
        return _Resp()

    monkeypatch.setattr("backend.core.llm_router.litellm.completion", fake_completion)

    out = router.execute_simple_task(
        system_prompt="sys",
        user_prompt="hello",
        model="openai/gpt-5.4",
    )

    assert out == "ok"
    assert captured["model"] == "openai/gpt-5.4"
    assert captured["api_base"] == "https://openrouter.ai/api/v1"
    assert captured["api_key"] == "sk-or-v1-test"


def test_kimi_routes_via_moonshot_openai_compatible_endpoint(monkeypatch):
    user = _make_user(
        llm_settings={},
        encrypted_api_keys={"kimi": "encrypted-placeholder"},
    )

    monkeypatch.setattr(
        "backend.core.llm_router.GameMasterLLM._get_decrypted_key",
        lambda self, provider: "sk-kimi-test",
    )
    router = GameMasterLLM(user, provider="kimi")

    captured = {}

    class _Msg:
        content = "ok"

    class _Choice:
        message = _Msg()

    class _Resp:
        choices = [_Choice()]

        @staticmethod
        def model_dump():
            return {}

    def fake_completion(**kwargs):
        captured.update(kwargs)
        return _Resp()

    monkeypatch.setattr("backend.core.llm_router.litellm.completion", fake_completion)

    out = router.execute_simple_task(
        system_prompt="sys",
        user_prompt="hello",
        model="moonshot-v1-8k",
    )

    assert out == "ok"
    assert captured["model"] == "moonshot-v1-8k"
    assert captured["custom_llm_provider"] == "openai"
    assert captured["api_base"] == "https://api.moonshot.ai/v1"
    assert captured["api_key"] == "sk-kimi-test"


def test_openrouter_retries_with_available_providers_on_provider_mismatch(monkeypatch):
    user = _make_user(
        llm_settings={},
        encrypted_api_keys={"openrouter": "encrypted-placeholder"},
    )
    monkeypatch.setattr(
        "backend.core.llm_router.GameMasterLLM._get_decrypted_key",
        lambda self, provider: "sk-or-v1-test",
    )
    router = GameMasterLLM(user, provider="openrouter")

    calls = []

    class _Msg:
        content = "ok"

    class _Choice:
        message = _Msg()

    class _Resp:
        choices = [_Choice()]

        @staticmethod
        def model_dump():
            return {}

    def fake_completion(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            raise Exception(
                "Error code: 404 - {'error': {'message': 'No allowed providers are available for the selected model.', "
                "'metadata': {'available_providers': ['xai'], 'requested_providers': ['openai']}}}"
            )
        return _Resp()

    monkeypatch.setattr("backend.core.llm_router.litellm.completion", fake_completion)

    out = router.execute_simple_task(
        system_prompt="sys",
        user_prompt="hello",
        model="openai/gpt-5-mini",
    )

    assert out == "ok"
    assert len(calls) == 2
    assert "extra_body" not in calls[0]
    assert calls[1]["extra_body"]["provider"]["order"] == ["xai"]
    assert calls[1]["extra_body"]["provider"]["allow_fallbacks"] is True


@pytest.mark.asyncio
async def test_openrouter_async_retries_with_available_providers_on_provider_mismatch(monkeypatch):
    user = _make_user(
        llm_settings={},
        encrypted_api_keys={"openrouter": "encrypted-placeholder"},
    )
    monkeypatch.setattr(
        "backend.core.llm_router.GameMasterLLM._get_decrypted_key",
        lambda self, provider: "sk-or-v1-test",
    )
    router = GameMasterLLM(user, provider="openrouter")

    calls = []

    class _Msg:
        content = "ok"

    class _Choice:
        message = _Msg()

    class _Resp:
        choices = [_Choice()]

        @staticmethod
        def model_dump():
            return {}

    async def fake_acompletion(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            raise Exception(
                "Error code: 404 - {'error': {'message': 'No allowed providers are available for the selected model.', "
                "'metadata': {'available_providers': ['xai'], 'requested_providers': ['openai']}}}"
            )
        return _Resp()

    monkeypatch.setattr("backend.core.llm_router.litellm.acompletion", fake_acompletion)

    out = await router.stream_simple_task(
        system_prompt="sys",
        user_prompt="hello",
        model="openai/gpt-5-mini",
    )

    assert out is not None
    assert len(calls) == 2
    assert "extra_body" not in calls[0]
    assert calls[1]["extra_body"]["provider"]["order"] == ["xai"]
    assert calls[1]["extra_body"]["provider"]["allow_fallbacks"] is True


@pytest.mark.asyncio
async def test_openrouter_routing_funnel_rejection_retries_without_provider_filter(monkeypatch):
    """When OpenRouter returns a routing funnel 404 (all candidates removed), retry without provider filter."""
    user = _make_user(
        llm_settings={
            "small_model_provider": "openrouter",
            "small_openrouter_provider": "NonExistentProvider",
        },
        encrypted_api_keys={"openrouter": "placeholder"},
    )
    monkeypatch.setattr(
        "backend.core.llm_router.GameMasterLLM._get_decrypted_key", lambda self, p: "sk-or-v1-test"
    )
    router = GameMasterLLM(user, provider="openrouter", model_category="small")

    calls = []

    class _Msg:
        content = "ok"

    class _Choice:
        message = _Msg()

    class _Resp:
        choices = [_Choice()]

        @staticmethod
        def model_dump():
            return {}

    async def fake_acompletion(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            raise Exception(
                "NotFoundError: OpenrouterException - {'error': {'message': "
                "'No endpoints found for openai/gpt-5-mini. Every candidate endpoint was removed during routing: "
                "Filter by Fallback removed openai.'}}"
            )
        return _Resp()

    monkeypatch.setattr("backend.core.llm_router.litellm.acompletion", fake_acompletion)

    out = await router.aexecute_simple_task(
        system_prompt="sys",
        user_prompt="hello",
        model="openai/gpt-5-mini",
    )

    assert out == "ok"
    assert len(calls) == 2
    # First call had restricted provider
    assert calls[0]["extra_body"]["provider"]["order"] == ["NonExistentProvider"]
    # Second retry call removed the provider restriction
    assert "provider" not in calls[1].get("extra_body", {})


def test_thinking_defaults_to_disabled_when_not_configured(monkeypatch):
    monkeypatch.setattr(
        "backend.core.llm_router.GameMasterLLM._get_decrypted_key",
        lambda self, provider: "test-key",
    )
    user = _make_user(llm_settings={"small_model": "gpt-4o-mini"})
    router = GameMasterLLM(user, provider="openai", model_category="small")
    assert router.enable_thinking is False


def test_thinking_string_false_is_treated_as_disabled(monkeypatch):
    monkeypatch.setattr(
        "backend.core.llm_router.GameMasterLLM._get_decrypted_key",
        lambda self, provider: "test-key",
    )
    user = _make_user(llm_settings={"small_enable_thinking": "false"})
    router = GameMasterLLM(user, provider="openai", model_category="small")
    assert router.enable_thinking is False


def test_thinking_string_true_is_treated_as_enabled(monkeypatch):
    monkeypatch.setattr(
        "backend.core.llm_router.GameMasterLLM._get_decrypted_key",
        lambda self, provider: "test-key",
    )
    user = _make_user(llm_settings={"small_enable_thinking": "true"})
    router = GameMasterLLM(user, provider="openai", model_category="small")
    assert router.enable_thinking is True


def test_invalid_thinking_value_logs_warning_and_falls_back_to_false(monkeypatch, caplog):
    monkeypatch.setattr(
        "backend.core.llm_router.GameMasterLLM._get_decrypted_key",
        lambda self, provider: "test-key",
    )
    user = _make_user(llm_settings={"small_enable_thinking": "definitely"})

    caplog.set_level("WARNING")
    router = GameMasterLLM(user, provider="openai", model_category="small")

    assert router.enable_thinking is False
    assert "Invalid thinking setting" in caplog.text


@pytest.mark.asyncio
async def test_aexecute_simple_task(monkeypatch):
    user = _make_user(
        encrypted_api_keys={"openai": "encrypted-placeholder"},
    )
    monkeypatch.setattr(
        "backend.core.llm_router.GameMasterLLM._get_decrypted_key", lambda self, provider: "sk-test"
    )
    router = GameMasterLLM(user, provider="openai")

    captured = {}

    class _Msg:
        content = "hello world"

    class _Choice:
        message = _Msg()

    class _Resp:
        choices = [_Choice()]

        @staticmethod
        def model_dump():
            return {}

    async def fake_acompletion(**kwargs):
        captured.update(kwargs)
        return _Resp()

    monkeypatch.setattr("backend.core.llm_router.litellm.acompletion", fake_acompletion)

    out = await router.aexecute_simple_task(
        system_prompt="sys",
        user_prompt="prompt",
        model="gpt-4o",
    )

    assert out == "hello world"
    assert captured["model"] == "gpt-4o"
    assert captured["custom_llm_provider"] == "openai"
    assert "stream" not in captured or captured["stream"] is False


@pytest.mark.asyncio
async def test_stream_simple_task_openai_non_prefixed_model_sets_provider(monkeypatch):
    user = _make_user(
        encrypted_api_keys={"openai": "encrypted-placeholder"},
    )
    monkeypatch.setattr(
        "backend.core.llm_router.GameMasterLLM._get_decrypted_key", lambda self, provider: "sk-test"
    )
    router = GameMasterLLM(user, provider="openai")

    captured = {}

    class _Msg:
        content = "hello stream"

    class _Choice:
        message = _Msg()

    class _Resp:
        choices = [_Choice()]

        @staticmethod
        def model_dump():
            return {}

    async def fake_acompletion(**kwargs):
        captured.update(kwargs)
        return _Resp()

    monkeypatch.setattr("backend.core.llm_router.litellm.acompletion", fake_acompletion)

    out = await router.stream_simple_task(
        system_prompt="sys",
        user_prompt="prompt",
        model="gpt-5.3",
    )

    assert out is not None
    assert captured["model"] == "gpt-5.3"
    assert captured["custom_llm_provider"] == "openai"
    assert captured["stream"] is True


@pytest.mark.asyncio
async def test_aexecute_complex_task_fallback_injects_schema_into_sent_system_prompt(monkeypatch):
    class _MiniSchema(BaseModel):
        required: str

    user = _make_user(encrypted_api_keys={"openai": "encrypted-placeholder"})
    monkeypatch.setattr(
        "backend.core.llm_router.GameMasterLLM._get_decrypted_key", lambda self, provider: "sk-test"
    )
    router = GameMasterLLM(user, provider="openai")

    captured = {}

    class _Msg:
        content = '{"required":"ok"}'

    class _Choice:
        message = _Msg()
        finish_reason = "stop"

    class _Resp:
        choices = [_Choice()]

        @staticmethod
        def model_dump():
            return {}

    async def fake_acompletion(**kwargs):
        captured.update(kwargs)
        return _Resp()

    monkeypatch.setattr("backend.core.llm_router.litellm.acompletion", fake_acompletion)

    out = await router.aexecute_complex_task(
        system_prompt="sys",
        user_prompt="prompt",
        response_model=_MiniSchema,
        model="claude-3-5-sonnet",
    )

    assert out.required == "ok"
    assert "SCHEMA:" in captured["messages"][0]["content"]


@pytest.mark.asyncio
async def test_aexecute_complex_task_gemini_direct_uses_structured_outputs(monkeypatch):
    class _MiniSchema(BaseModel):
        required: str

    user = _make_user(encrypted_api_keys={"google": "encrypted-placeholder"})
    monkeypatch.setattr(
        "backend.core.llm_router.GameMasterLLM._get_decrypted_key", lambda self, provider: "sk-test"
    )
    router = GameMasterLLM(user, provider="google")

    captured = {}

    class _Msg:
        content = '{"required":"ok"}'

    class _Choice:
        message = _Msg()
        finish_reason = "stop"

    class _Resp:
        choices = [_Choice()]

        @staticmethod
        def model_dump():
            return {}

    async def fake_acompletion(**kwargs):
        captured.update(kwargs)
        return _Resp()

    monkeypatch.setattr("backend.core.llm_router.litellm.acompletion", fake_acompletion)

    out = await router.aexecute_complex_task(
        system_prompt="sys",
        user_prompt="prompt",
        response_model=_MiniSchema,
        model="gemini-3.1-pro-preview",
    )

    assert out.required == "ok"
    # Direct Gemini should pass response_model directly as response_format
    assert captured["response_format"] == _MiniSchema


@pytest.mark.asyncio
async def test_aexecute_complex_task_kimi_uses_json_mode_fallback(monkeypatch):
    class _MiniSchema(BaseModel):
        title: str

    user = _make_user(
        encrypted_api_keys={"kimi": "encrypted-placeholder"},
    )
    monkeypatch.setattr(
        "backend.core.llm_router.GameMasterLLM._get_decrypted_key",
        lambda self, provider: "sk-kimi-test",
    )
    router = GameMasterLLM(user, provider="kimi")

    captured = {}

    class _Msg:
        content = '{"title":"ok"}'

    class _Choice:
        message = _Msg()
        finish_reason = "stop"

    class _Resp:
        choices = [_Choice()]

        @staticmethod
        def model_dump():
            return {}

    async def fake_acompletion(**kwargs):
        captured.update(kwargs)
        return _Resp()

    monkeypatch.setattr("backend.core.llm_router.litellm.acompletion", fake_acompletion)

    out = await router.aexecute_complex_task(
        system_prompt="sys",
        user_prompt="prompt",
        response_model=_MiniSchema,
        model="kimi-k2.6",
    )

    assert out.title == "ok"
    assert captured["response_format"] == {"type": "json_object"}
    assert "SCHEMA:" in captured["messages"][0]["content"]
    assert captured["api_base"] == "https://api.moonshot.ai/v1"


@pytest.mark.asyncio
async def test_aexecute_complex_task_surfaces_schema_validation_failure(monkeypatch):
    class _MiniSchema(BaseModel):
        required: str

    user = _make_user(encrypted_api_keys={"openai": "encrypted-placeholder"})
    monkeypatch.setattr(
        "backend.core.llm_router.GameMasterLLM._get_decrypted_key", lambda self, provider: "sk-test"
    )
    router = GameMasterLLM(user, provider="openai")

    class _Msg:
        content = "{}"

    class _Choice:
        message = _Msg()
        finish_reason = "stop"

    class _Resp:
        choices = [_Choice()]

        @staticmethod
        def model_dump():
            return {}

    async def fake_acompletion(**kwargs):
        return _Resp()

    monkeypatch.setattr("backend.core.llm_router.litellm.acompletion", fake_acompletion)

    with pytest.raises(ValueError, match="does not match expected schema"):
        await router.aexecute_complex_task(
            system_prompt="sys",
            user_prompt="prompt",
            response_model=_MiniSchema,
            model="claude-3-5-sonnet",
        )


@pytest.mark.asyncio
async def test_aexecute_complex_task_treats_empty_cleaned_content_as_no_content(monkeypatch):
    class _MiniSchema(BaseModel):
        required: str

    user = _make_user(encrypted_api_keys={"openai": "encrypted-placeholder"})
    monkeypatch.setattr(
        "backend.core.llm_router.GameMasterLLM._get_decrypted_key", lambda self, provider: "sk-test"
    )
    router = GameMasterLLM(user, provider="openai")

    class _Msg:
        content = "```json\n```"

    class _Choice:
        message = _Msg()
        finish_reason = "stop"

    class _Resp:
        choices = [_Choice()]

        @staticmethod
        def model_dump():
            return {}

    async def fake_acompletion(**kwargs):
        return _Resp()

    monkeypatch.setattr("backend.core.llm_router.litellm.acompletion", fake_acompletion)

    with pytest.raises(ValueError, match="No content returned from LLM for complex task"):
        await router.aexecute_complex_task(
            system_prompt="sys",
            user_prompt="prompt",
            response_model=_MiniSchema,
            model="claude-3-5-sonnet",
        )


def test_openrouter_provider_routing_single_provider(monkeypatch):
    """When openrouter_provider is set, GameMasterLLM injects the provider order and allow_fallbacks=False."""
    user = _make_user(
        llm_settings={
            "small_model_provider": "openrouter",
            "small_openrouter_provider": "Together",
        },
        encrypted_api_keys={"openrouter": "placeholder"},
    )
    monkeypatch.setattr(
        "backend.core.llm_router.GameMasterLLM._get_decrypted_key", lambda self, p: "sk-or-v1-test"
    )
    router = GameMasterLLM(user, provider="openrouter", model_category="small")

    captured = {}

    class _Msg:
        content = "ok"

    class _Choice:
        message = _Msg()

    class _Resp:
        choices = [_Choice()]

        @staticmethod
        def model_dump():
            return {}

    def fake_completion(**kwargs):
        captured.update(kwargs)
        return _Resp()

    monkeypatch.setattr("backend.core.llm_router.litellm.completion", fake_completion)

    router.execute_simple_task(
        system_prompt="sys",
        user_prompt="prompt",
        model="meta-llama/llama-3-8b-instruct",
    )

    assert "extra_body" in captured
    assert captured["extra_body"]["provider"] == {
        "order": ["Together"],
        "allow_fallbacks": False,
    }


@pytest.mark.asyncio
async def test_openrouter_provider_routing_comma_separated(monkeypatch):
    """Multiple comma-separated providers are trimmed and passed in order."""
    user = _make_user(
        llm_settings={
            "complex_model_provider": "openrouter",
            "complex_openrouter_provider": "Together, grok, alibaba",
        },
        encrypted_api_keys={"openrouter": "placeholder"},
    )
    monkeypatch.setattr(
        "backend.core.llm_router.GameMasterLLM._get_decrypted_key", lambda self, p: "sk-or-v1-test"
    )
    router = GameMasterLLM(user, provider="openrouter", model_category="complex")

    captured = {}

    class _Msg:
        content = "ok"

    class _Choice:
        message = _Msg()

    class _Resp:
        choices = [_Choice()]

        @staticmethod
        def model_dump():
            return {}

    async def fake_acompletion(**kwargs):
        captured.update(kwargs)
        return _Resp()

    monkeypatch.setattr("backend.core.llm_router.litellm.acompletion", fake_acompletion)

    await router.aexecute_simple_task(
        system_prompt="sys",
        user_prompt="prompt",
        model="meta-llama/llama-3-8b-instruct",
    )

    assert "extra_body" in captured
    assert captured["extra_body"]["provider"] == {
        "order": ["Together", "grok", "alibaba"],
        "allow_fallbacks": False,
    }


def test_openrouter_no_provider_routing_when_empty(monkeypatch):
    """When openrouter_provider is not set or whitespace-only, no provider routing block is injected."""
    user = _make_user(
        llm_settings={
            "small_model_provider": "openrouter",
            "small_openrouter_provider": "   ",
        },
        encrypted_api_keys={"openrouter": "placeholder"},
    )
    monkeypatch.setattr(
        "backend.core.llm_router.GameMasterLLM._get_decrypted_key", lambda self, p: "sk-or-v1-test"
    )
    router = GameMasterLLM(user, provider="openrouter", model_category="small")

    captured = {}

    class _Msg:
        content = "ok"

    class _Choice:
        message = _Msg()

    class _Resp:
        choices = [_Choice()]

        @staticmethod
        def model_dump():
            return {}

    def fake_completion(**kwargs):
        captured.update(kwargs)
        return _Resp()

    monkeypatch.setattr("backend.core.llm_router.litellm.completion", fake_completion)

    router.execute_simple_task(
        system_prompt="sys",
        user_prompt="prompt",
        model="meta-llama/llama-3-8b-instruct",
    )

    assert captured.get("extra_body") is None or "provider" not in captured.get("extra_body", {})


@pytest.mark.asyncio
async def test_acompletion_retries_on_transient_socket_timeout(monkeypatch):
    """When a stale pooled socket causes an immediate 0.015s Timeout, acompletion retries with a fresh connection."""
    import litellm

    user = _make_user(
        llm_settings={"complex_model_provider": "deepseek"},
        encrypted_api_keys={"deepseek": "placeholder"},
    )
    monkeypatch.setattr(
        "backend.core.llm_router.GameMasterLLM._get_decrypted_key", lambda self, p: "sk-test"
    )
    router = GameMasterLLM(user, provider="deepseek", model_category="complex")

    call_count = 0

    class _Msg:
        content = "recovered successfully"

    class _Choice:
        message = _Msg()

    class _Resp:
        choices = [_Choice()]

        @staticmethod
        def model_dump():
            return {}

    async def fake_acompletion(**kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise litellm.Timeout(
                "DeepseekException - Connection timed out. Timeout passed=60.0, time taken=0.015 seconds",
                model="deepseek-chat",
                llm_provider="deepseek",
            )
        return _Resp()

    monkeypatch.setattr("backend.core.llm_router.litellm.acompletion", fake_acompletion)

    out = await router.aexecute_simple_task(
        system_prompt="sys",
        user_prompt="prompt",
        model="deepseek-chat",
    )

    assert call_count == 2
    assert out == "recovered successfully"


def test_completion_retries_on_transient_socket_timeout(monkeypatch):
    """Sync completion also recovers on transient connection/timeout drops."""
    import litellm

    user = _make_user(
        llm_settings={"small_model_provider": "openai"},
        encrypted_api_keys={"openai": "placeholder"},
    )
    monkeypatch.setattr(
        "backend.core.llm_router.GameMasterLLM._get_decrypted_key", lambda self, p: "sk-test"
    )
    router = GameMasterLLM(user, provider="openai", model_category="small")

    call_count = 0

    class _Msg:
        content = "sync recovered"

    class _Choice:
        message = _Msg()

    class _Resp:
        choices = [_Choice()]

        @staticmethod
        def model_dump():
            return {}

    def fake_completion(**kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise litellm.APIConnectionError(
                "Connection closed by peer", model="gpt-4o", llm_provider="openai"
            )
        return _Resp()

    monkeypatch.setattr("backend.core.llm_router.litellm.completion", fake_completion)

    out = router.execute_simple_task(
        system_prompt="sys",
        user_prompt="prompt",
        model="gpt-4o",
    )

    assert call_count == 2
    assert out == "sync recovered"


def test_openrouter_model_normalization_adds_author_prefix(monkeypatch):
    user = _make_user(encrypted_api_keys={"openrouter": "encrypted-placeholder"})
    monkeypatch.setattr(
        "backend.core.llm_router.GameMasterLLM._get_decrypted_key", lambda self, p: "sk-or-v1-test"
    )
    router = GameMasterLLM(user, provider="openrouter")

    assert router._normalize_model("gpt-4o-mini") == "openai/gpt-4o-mini"
    assert router._normalize_model("openrouter/gpt-4o-mini") == "openai/gpt-4o-mini"
    assert router._normalize_model("claude-3-5-sonnet") == "anthropic/claude-3-5-sonnet"
    assert router._normalize_model("anthropic/claude-3-haiku") == "anthropic/claude-3-haiku"
    assert router._normalize_model("gemini-2.5-flash") == "google/gemini-2.5-flash"
    assert router._normalize_model("deepseek-chat") == "deepseek/deepseek-chat"


@pytest.mark.parametrize(
    ("role_url", "global_url", "expected"),
    [
        ("http://mechanics:11434/", "http://shared:11434", "http://mechanics:11434"),
        ("", "http://shared:11434/", "http://shared:11434"),
        (None, None, "http://localhost:11434"),
    ],
)
def test_ollama_role_url_precedence(role_url, global_url, expected):
    router = GameMasterLLM(
        _make_user(
            {
                "small_model_provider": "ollama",
                "small_ollama_url": role_url,
                "ollama_url": global_url,
            }
        ),
        provider="ollama",
    )
    assert router.api_base == expected


@pytest.mark.parametrize("category", ["small", "complex", "generator", "compression"])
def test_ollama_roles_are_isolated_and_preserve_other_categories(category):
    from backend.core.config import settings

    user = _make_user(
        {
            "ollama_url": "http://shared:11434",
            "small_model_provider": "ollama",
            "small_ollama_url": "http://mechanics:11434",
            "small_ollama_timeout": 90,
            "small_ollama_num_ctx": 8192,
            "complex_model_provider": "ollama",
            "complex_ollama_url": "http://narration:11434",
            "complex_ollama_timeout": 150,
            "complex_ollama_num_ctx": 32768,
        }
    )
    router = GameMasterLLM(user, provider="ollama", model_category=category)
    expected = {
        "small": ("http://mechanics:11434", 90, 8192),
        "complex": ("http://narration:11434", 150, 32768),
    }
    if category in expected:
        assert (router.api_base, router.request_timeout, router.ollama_num_ctx) == expected[
            category
        ]
        return
    assert router.api_base == "http://shared:11434"
    assert router.ollama_num_ctx is None
    assert router.request_timeout == (
        settings.WORLDBUILDING_TIMEOUT if category == "generator" else settings.INTELLIGENCE_TIMEOUT
    )


def test_agent_ollama_does_not_inherit_another_small_provider(monkeypatch):
    from backend.core.config import settings

    user = _make_user(
        {
            "ollama_url": "http://shared:11434",
            "small_model_provider": "openai",
            "small_ollama_url": "http://wrong:11434",
            "small_ollama_timeout": 60,
            "small_ollama_num_ctx": 8192,
        }
    )
    router = GameMasterLLM(user, provider="ollama", model_category="small")
    assert router.api_base == "http://shared:11434"
    assert router.request_timeout == settings.INTELLIGENCE_TIMEOUT
    assert router.ollama_num_ctx is None
    monkeypatch.setattr(GameMasterLLM, "_get_decrypted_key", lambda self, provider: "fake")
    cloud = GameMasterLLM(user, provider="openai", model_category="small")
    assert cloud.api_base is None
    assert cloud.request_timeout == settings.INTELLIGENCE_TIMEOUT
    assert cloud.ollama_num_ctx is None


@pytest.mark.asyncio
@pytest.mark.parametrize("num_ctx", [None, 8192])
async def test_all_ollama_request_paths_use_shared_options(monkeypatch, num_ctx):
    from types import SimpleNamespace

    class Answer(BaseModel):
        value: int

    router = GameMasterLLM(
        _make_user(
            {
                "small_model_provider": "ollama",
                "small_ollama_url": "http://role:11434",
                "small_ollama_timeout": 60,
                "small_ollama_num_ctx": num_ctx,
                "small_max_tokens": 777,
            }
        ),
        provider="ollama",
    )
    calls = []
    helper_calls = []
    apply_options = router._apply_ollama_options

    def spy(kwargs, model):
        helper_calls.append(model)
        apply_options(kwargs, model)

    def response(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content='{"value": 42}'), finish_reason="stop"
                )
            ],
            model_dump=lambda: {},
        )

    async def chunks():
        yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="hello"))])

    async def async_response(**kwargs):
        if kwargs.get("stream"):
            calls.append(kwargs)
            return chunks()
        return response(**kwargs)

    monkeypatch.setattr(router, "_apply_ollama_options", spy)
    monkeypatch.setattr("backend.core.llm_router.litellm.completion", response)
    monkeypatch.setattr("backend.core.llm_router.litellm.acompletion", async_response)
    router.execute_simple_task("sys", "hi", "role-model:latest")
    await router.aexecute_simple_task("sys", "hi", "role-model:latest")
    stream = await router.stream_simple_task("sys", "hi", "role-model:latest")
    assert [chunk async for chunk in stream]
    assert router.execute_complex_task("sys", "hi", Answer, "role-model:latest").value == 42
    assert (
        await router.aexecute_complex_task("sys", "hi", Answer, "role-model:latest")
    ).value == 42
    assert len(calls) == len(helper_calls) == 5
    for call in calls:
        assert call["api_base"] == "http://role:11434"
        assert call["custom_llm_provider"] == "ollama"
        assert call["think"] is False
        assert call["request_timeout"] == 60
        assert call["max_tokens"] == 777
        assert "extra_body" not in call
        assert call.get("num_ctx") == num_ctx
        assert ("num_ctx" in call) == (num_ctx is not None)


@pytest.mark.parametrize(
    "content,expected",
    [
        ("Internal planning.\n</think>\nMira found a key.", "Mira found a key."),
        ("<think>Internal planning.</think>Mira found a key.", "Mira found a key."),
        ("Mira found a key.", "Mira found a key."),
    ],
)
def test_thinking_cleanup_handles_an_opening_tag_supplied_by_the_template(content, expected):
    assert GameMasterLLM.clean_thinking_tags(content) == expected
