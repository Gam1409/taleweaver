"""The normal provider adapters transmit request-scoped schemas without new calls."""

import json

import httpx
import pytest

from backend.core.llm_router import GameMasterLLM
from backend.models.user import User
from tests.test_llm_structured_http import Reply, response, wire_schema


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
async def test_structured_router_transmits_supplied_schema_with_real_adapter(
    monkeypatch, provider, model
):
    seen = []

    async def handle(_client, request, **_kwargs):
        seen.append(json.loads(request.content))
        return httpx.Response(200, json=response(provider), request=request)

    def forbid(*_args, **_kwargs):
        raise AssertionError("No real socket is allowed in provider contract tests.")

    monkeypatch.setattr(httpx.AsyncClient, "send", handle)
    monkeypatch.setattr("socket.socket.connect", forbid)
    monkeypatch.setattr(GameMasterLLM, "_get_decrypted_key", lambda *_: "test-key")
    user = User(
        username="test",
        llm_settings={"ollama_url": "http://127.0.0.1:11434"},
        encrypted_api_keys={provider: "test-placeholder"},
    )
    router = GameMasterLLM(user, provider=provider)
    router.model, router.request_timeout = model, 5
    schema = Reply.model_json_schema()
    schema["properties"]["actor_id"]["enum"] = ["known_npc"]
    reply = await router.aexecute_complex_task(
        "Return JSON.", "Extract.", Reply, model, response_schema=schema
    )
    assert reply.actor_id == "known_npc" and len(seen) == 1
    if provider == "deepseek":
        assert seen[0]["response_format"] == {"type": "json_object"}
        assert "known_npc" in str(seen[0]["messages"])
    else:
        assert wire_schema(provider, seen[0])["properties"]["actor_id"]["enum"] == ["known_npc"]
    assert "enum" not in Reply.model_json_schema()["properties"]["actor_id"]
