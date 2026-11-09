"""The configured custom endpoint JSON mode also applies to technical NPC calls."""

import json
from types import SimpleNamespace

import httpx
import pytest

from backend.engine.chpm import inference, json_contract
from backend.engine.chpm.schema import Projection, Settings, Usage
from tests.test_custom_openai import local_policy, make_router

__all__ = ["local_policy"]
BODY = '{"audience":[{"actor_id":"npc","quotes":["Hello"],"uncertain":false}]}'


@pytest.mark.parametrize("mode", ["prompt", "json_object", "json_schema"])
async def test_configured_json_mode_reaches_technical_http_requests_only(
    monkeypatch, local_policy, mode
):
    seen = []

    async def handle(_transport, request):
        body = json.loads(request.content)
        seen.append(body)
        narrative = body["messages"][0]["content"] == "Freeform narrative."
        return httpx.Response(
            200,
            json={
                "id": "test-completion",
                "object": "chat.completion",
                "model": "vendor/model",
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": "A freeform answer." if narrative else BODY,
                        },
                        "finish_reason": "stop",
                    }
                ],
            },
        )

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", handle)
    router = make_router()
    router.model = "vendor/model"
    router.custom_response_format = mode
    host = SimpleNamespace(user=None, game_id=None, _chpm_model_factory=lambda _role: router)
    identifiers = {"actor_id": ["npc"]}
    usage = Usage()
    result = await inference.request(
        host,
        Settings(),
        usage,
        "Classify this JSON input.",
        {},
        Projection,
        "perception",
        identifiers=identifiers,
    )
    assert result.audience[0].actor_id == "npc"
    assert usage.calls == 1 and len(seen) == 1
    if mode == "prompt":
        assert "response_format" not in seen[0]
    else:
        assert seen[0]["response_format"]["type"] == mode
    if mode == "json_schema":
        assert seen[0]["response_format"]["json_schema"]["schema"] == json_contract.response_schema(
            Projection, identifiers
        )
    assert (
        await router.aexecute_simple_task("Freeform narrative.", "Continue.", "vendor/model")
        == "A freeform answer."
    )
    assert "response_format" not in seen[1]
