"""The configured custom endpoint JSON mode also applies to technical NPC calls."""

import json
from types import SimpleNamespace

import httpx
import pytest

from backend.engine.chpm import inference, json_contract
from backend.engine.chpm.proposal_draft import Draft
from backend.engine.chpm.schema import Projection, Settings, Usage
from tests.test_chpm_kernel import wire_proposal
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
        sent = seen[0]["response_format"]["json_schema"]["schema"]
        assert sent["$defs"]["Perception"]["properties"]["actor_id"]["enum"] == ["npc"]
        assert sent["$defs"]["Perception"]["additionalProperties"] is False
        assert sent["properties"]["audience"]["maxItems"] == 20
    assert (
        await router.aexecute_simple_task("Freeform narrative.", "Continue.", "vendor/model")
        == "A freeform answer."
    )
    assert "response_format" not in seen[1]


async def test_finite_candidate_keys_reach_the_http_grammar_without_expanding_instructions(
    monkeypatch, local_policy
):
    seen = []

    async def handle(_transport, request):
        seen.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "id": "test-completion",
                "object": "chat.completion",
                "model": "vendor/model",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": json.dumps(wire_proposal())},
                        "finish_reason": "stop",
                    }
                ],
            },
        )

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", handle)
    router = make_router()
    router.model, router.custom_response_format = "vendor/model", "json_schema"
    host = SimpleNamespace(user=None, game_id=None, _chpm_model_factory=lambda _role: router)
    identifiers = {"motive_ids": ["goal1", "character"]}
    usage = Usage()
    await inference.request(
        host, Settings(), usage, "Choose an action.", {}, Draft, "proposal", identifiers=identifiers
    )
    assert usage.calls == 1 and len(seen) == 1
    sent = seen[0]["response_format"]["json_schema"]["schema"]
    assert sent["$defs"]["ChoicePreference"]["properties"]["motive_ids"]["items"]["enum"] == [
        "goal1",
        "character",
    ]
    assert sent["properties"]["candidates"]["additionalProperties"] is False
    assert "CONTINUE" in sent["properties"]["candidates"]["properties"]
    compact = json_contract.response_schema(Draft, identifiers)
    assert seen[0]["messages"][0]["content"].endswith(
        json.dumps(compact, ensure_ascii=False, separators=(",", ":"))
    )
