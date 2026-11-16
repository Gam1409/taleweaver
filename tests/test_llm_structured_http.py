"""Exercise real LiteLLM adapters against mock HTTP, never a paid model."""

import json
from types import SimpleNamespace

import httpx
import pytest

from backend.core.llm_router import GameMasterLLM
from backend.engine.chpm.inference import request
from backend.engine.chpm.schema import Settings, Usage
from backend.models.user import User
from tests.test_llm_structured_output import Reply

BODY = '{"actor_id":"known_npc"}'


def response(provider):
    if provider == "ollama":
        return {
            "model": "local-model",
            "done": True,
            "response": BODY,
            "message": {"role": "assistant", "content": BODY},
            "eval_count": 10,
            "prompt_eval_count": 10,
        }
    if provider == "google":
        return {
            "candidates": [
                {"content": {"role": "model", "parts": [{"text": BODY}]}, "finishReason": "STOP"}
            ],
            "usageMetadata": {
                "promptTokenCount": 10,
                "candidatesTokenCount": 10,
                "totalTokenCount": 20,
            },
        }
    if provider == "anthropic":
        return {
            "id": "msg_test",
            "type": "message",
            "role": "assistant",
            "model": "claude-sonnet-4-5-20250929",
            "stop_reason": "end_turn",
            "content": [{"type": "text", "text": BODY}],
            "usage": {"input_tokens": 10, "output_tokens": 10},
        }
    return {
        "id": "completion_test",
        "object": "chat.completion",
        "model": "test-model",
        "choices": [
            {"index": 0, "message": {"role": "assistant", "content": BODY}, "finish_reason": "stop"}
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 10},
    }


def wire_schema(provider, body):
    if provider == "ollama":
        return body.get("format")
    if provider == "google":
        config = body.get("generationConfig", {})
        assert (
            config.get("response_mime_type") or config.get("responseMimeType")
        ) == "application/json"
        return (
            config.get("response_json_schema")
            or config.get("responseJsonSchema")
            or config.get("response_schema")
            or config.get("responseSchema")
        )
    if provider == "anthropic":
        if body.get("output_format"):
            return body["output_format"]["schema"]
        if body.get("output_config"):
            return body["output_config"]["format"]["schema"]
        return body["tools"][0]["input_schema"]
    return body.get("response_format", {}).get("json_schema", {}).get("schema")


@pytest.mark.parametrize(
    "provider,model",
    [
        ("ollama", "local-model"),
        ("openai", "gpt-4o-mini"),
        ("google", "gemini-2.5-flash"),
        ("anthropic", "claude-sonnet-4-5-20250929"),
        ("deepseek", "deepseek-chat"),
    ],
)
async def test_provider_adapter_receives_technical_contract_and_one_call(
    monkeypatch, provider, model
):
    seen = []

    async def handle(_client, http_request, **_kwargs):
        seen.append(json.loads(http_request.content))
        return httpx.Response(200, json=response(provider), request=http_request)

    def forbid_network(*_args, **_kwargs):
        raise AssertionError("The provider HTTP test must never open a network socket.")

    monkeypatch.setattr(httpx.AsyncClient, "send", handle)
    monkeypatch.setattr("socket.socket.connect", forbid_network)
    monkeypatch.setattr(GameMasterLLM, "_get_decrypted_key", lambda *_args: "test-key")
    user = User(
        username="test",
        llm_settings={"ollama_url": "http://127.0.0.1:11434"},
        encrypted_api_keys={provider: "test-placeholder"},
    )
    router = GameMasterLLM(user, provider=provider)
    router.model = model
    router.request_timeout = 5
    host = SimpleNamespace(user=user, game_id=None, _chpm_model_factory=lambda _role: router)
    usage = Usage()
    result = await request(
        host,
        Settings(),
        usage,
        "Return the known actor.",
        {},
        Reply,
        "test",
        identifiers={"actor_id": ["known_npc"]},
    )
    assert result.actor_id == "known_npc"
    assert len(seen) == usage.calls == 1
    if provider == "deepseek":
        assert seen[0]["response_format"] == {"type": "json_object"}
    else:
        schema = wire_schema(provider, seen[0])
        assert schema["properties"]["actor_id"]["enum"] == ["known_npc"]
        assert schema["additionalProperties"] is False
    await router.aexecute_simple_task("Freeform narrative.", "Continue.", model)
    assert len(seen) == 2
    assert "response_format" not in seen[1] and "format" not in seen[1]
    assert "output_format" not in seen[1] and "output_config" not in seen[1]
    assert "responseMimeType" not in seen[1].get("generationConfig", {})
    assert "response_mime_type" not in seen[1].get("generationConfig", {})
    assert "tools" not in seen[1]
