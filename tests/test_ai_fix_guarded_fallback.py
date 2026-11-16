"""AI Fix fallback obeys the same durable reservation policy as its transport."""

import asyncio
from types import SimpleNamespace

import pytest

from backend.api.routes.adventures.editing.ai_fix_fallback import reject_uncertain_fallback
from backend.api.routes.adventures.editing.ai_fix_llm import _generate_llm_proposals
from backend.core.config import settings
from backend.core.inference import admission, receipts, transport
from backend.core.inference.registry import (
    InferenceQueueError,
    InferenceUncertainError,
    Registry,
    endpoint_key,
)
from backend.core.llm_parallel import ParallelPolicy
from backend.core.llm_router import GameMasterLLM
from backend.models.user import User
from tests.test_ai_fix_fallback_policy import Reply


@pytest.mark.parametrize("enabled", [False, True])
async def test_configured_policy_blocks_fallback_while_primary_transport_is_running(
    monkeypatch, tmp_path, enabled
):
    monkeypatch.setattr(settings, "INFERENCE_SERIALIZATION_ENABLED", False)
    monkeypatch.setattr(settings, "AI_FIX_FALLBACK_PROVIDER", "")
    registry = Registry(tmp_path / "requests.json")
    monkeypatch.setattr(admission, "_registry", registry)
    release = asyncio.Event()
    calls = []

    async def complete(**kwargs):
        calls.append(kwargs["api_base"])
        if kwargs["api_base"].endswith(":11111"):
            await release.wait()
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content='{"value":"ok"}'), finish_reason="stop"
                )
            ],
            model_dump=lambda: {},
        )

    monkeypatch.setattr(
        GameMasterLLM,
        "_get_litellm",
        classmethod(lambda _cls: SimpleNamespace(acompletion=complete)),
    )
    config = {
        "complex_model_provider": "ollama",
        "complex_model": "test",
        "complex_ollama_url": "http://127.0.0.1:11111",
        "small_model_provider": "ollama",
        "small_model": "test",
        "small_ollama_url": "http://127.0.0.1:22222",
        "parallel_requests": {
            "roles": {"complex": {"enabled": enabled}, "small": {"enabled": enabled}}
        },
    }
    try:
        with pytest.raises(InferenceQueueError, match="still being monitored"):
            await _generate_llm_proposals(
                user_prompt="Fixture",
                current_user=User(username="fixture", llm_settings=config),
                response_model=Reply,
                gm_kwargs={"system_prompt": "Return the fixture."},
                timeout_seconds=0.02,
            )
        assert len(calls) == 1
        assert registry.status()[0]["status"] == "RUNNING"
    finally:
        release.set()
        await asyncio.gather(*tuple(receipts._monitors))
    assert registry.status() == []


@pytest.mark.parametrize("uncertain", [False, True])
def test_effective_provider_endpoint_and_unrelated_origins_are_distinguished(
    monkeypatch, tmp_path, uncertain
):
    monkeypatch.setattr(settings, "INFERENCE_SERIALIZATION_ENABLED", False)
    registry = Registry(tmp_path / "requests.json")
    monkeypatch.setattr(admission, "_registry", registry)
    client = SimpleNamespace(
        provider="minimax",
        api_base=None,
        minimax_api_base="https://fixture.invalid/v1",
        parallel_policy=ParallelPolicy(enabled=False),
    )
    ticket = registry.enqueue(endpoint_key("https://fixture.invalid/v1"), capacity=1)
    assert registry.try_acquire(ticket)
    if uncertain:
        registry.finish(ticket, certain=False)
    with pytest.raises(InferenceUncertainError if uncertain else InferenceQueueError):
        reject_uncertain_fallback(client, TimeoutError())
    client.minimax_api_base = "https://other.invalid/v1"
    reject_uncertain_fallback(client, TimeoutError())
    registry.finish(ticket, certain=True)


def test_no_policy_and_disabled_legacy_preserve_unguarded_fallback(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "INFERENCE_SERIALIZATION_ENABLED", False)
    registry = Registry(tmp_path / "requests.json")
    monkeypatch.setattr(admission, "_registry", registry)
    client = SimpleNamespace(
        provider="ollama", api_base="http://fixture.invalid", parallel_policy=None
    )
    ticket = registry.enqueue(endpoint_key(client.api_base))
    assert registry.try_acquire(ticket)
    reject_uncertain_fallback(client, TimeoutError())
    registry.finish(ticket, certain=True)


def test_autodetected_openrouter_origin_matches_the_guarded_dispatch(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "INFERENCE_SERIALIZATION_ENABLED", False)
    monkeypatch.setattr(GameMasterLLM, "_get_decrypted_key", lambda *_args: "sk-or-v1-synthetic")
    client = GameMasterLLM.for_role(
        User(
            llm_settings={
                "complex_model_provider": "openai",
                "complex_model": "gpt-fixture",
                "parallel_requests": {"roles": {"complex": {"enabled": False}}},
            }
        ),
        "complex",
    )
    options = {}
    client._apply_provider_options(options, client.model)
    assert options["api_base"] == "https://openrouter.ai/api/v1"
    registry = Registry(tmp_path / "requests.json")
    monkeypatch.setattr(admission, "_registry", registry)
    ticket = registry.enqueue(transport.target(client, options), capacity=1)
    assert registry.try_acquire(ticket)
    try:
        with pytest.raises(InferenceQueueError, match="still being monitored"):
            reject_uncertain_fallback(client, TimeoutError())
    finally:
        registry.finish(ticket, certain=True)


@pytest.mark.parametrize("provider", ["openai", "deepseek", "minimax", "kimi", "anthropic"])
@pytest.mark.parametrize("autodetect_key", [False, True])
def test_configured_origin_matches_wire_options_for_native_and_routed_providers(
    monkeypatch, provider, autodetect_key
):
    key = "sk-or-v1-synthetic" if autodetect_key else "synthetic-key"
    monkeypatch.setattr(GameMasterLLM, "_get_decrypted_key", lambda *_args: key)
    client = GameMasterLLM.for_role(
        User(
            llm_settings={
                "complex_model_provider": provider,
                "complex_model": "fixture-model",
                "parallel_requests": {"roles": {"complex": {"enabled": False}}},
            }
        ),
        "complex",
    )
    options = {}
    client._apply_provider_options(options, client.model)
    assert transport.target(client) is not None
    assert transport.target(client) == transport.target(client, options)
