"""Configured MiniMax M3 thinking controls must survive the real HTTP adapter."""

import json

import httpx
import pytest

from backend.core.llm_router import GameMasterLLM
from backend.models.user import User
from tests.test_deepseek_thinking import Answer


async def _execute_path(client, method):
    if method == "text":
        assert (
            client.execute_simple_task("Fixture", "Return JSON", client.model) == '{"value":"ok"}'
        )
        return
    if method == "async_text":
        assert (
            await client.aexecute_simple_task("Fixture", "Return JSON", client.model)
            == '{"value":"ok"}'
        )
        return
    if method == "structured":
        assert client.execute_complex_task(
            "Fixture", "Return JSON", Answer, client.model
        ) == Answer(value="ok")
        return
    if method == "async_structured":
        assert await client.aexecute_complex_task(
            "Fixture", "Return JSON", Answer, client.model
        ) == Answer(value="ok")
        return
    stream = await client.stream_simple_task("Fixture", "Return JSON", client.model)
    assert [chunk async for chunk in stream]


@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.parametrize("model", ["MiniMax-M3", "MiniMax-M2.7"])
@pytest.mark.parametrize(
    "method", ["text", "async_text", "structured", "async_structured", "stream"]
)
async def test_minimax_thinking_reaches_supported_real_adapters(
    monkeypatch, enabled, method, model
):
    seen = []

    def reply(request):
        body = json.loads(request.content)
        seen.append(body)
        message = {"role": "assistant", "content": '{"value":"ok"}'}
        if body.get("stream"):
            chunk = {
                "id": "fixture",
                "object": "chat.completion.chunk",
                "model": model,
                "choices": [{"index": 0, "delta": message, "finish_reason": "stop"}],
            }
            return httpx.Response(
                200,
                content=f"data: {json.dumps(chunk)}\n\ndata: [DONE]\n\n".encode(),
                headers={"content-type": "text/event-stream"},
                request=request,
            )
        return httpx.Response(
            200,
            json={
                "id": "fixture",
                "object": "chat.completion",
                "model": model,
                "choices": [{"index": 0, "message": message, "finish_reason": "stop"}],
            },
            request=request,
        )

    async def send(_client, request, **_kwargs):
        return reply(request)

    def sync_send(_client, request, **_kwargs):
        return reply(request)

    def forbid_network(*_args, **_kwargs):
        raise AssertionError("The adapter regression must not open network sockets.")

    monkeypatch.setattr(httpx.AsyncClient, "send", send)
    monkeypatch.setattr(httpx.Client, "send", sync_send)
    monkeypatch.setattr("socket.socket.connect", forbid_network)
    monkeypatch.setattr(GameMasterLLM, "_get_decrypted_key", lambda *_args: "fixture-key")
    client = GameMasterLLM.for_role(
        User(
            llm_settings={
                "small_model_provider": "minimax",
                "small_model": model,
                "small_enable_thinking": enabled,
            }
        ),
        "small",
    )
    client.request_timeout = 3
    await _execute_path(client, method)
    assert len(seen) == 1
    if model == "MiniMax-M3":
        assert seen[0].get("thinking") == {"type": "adaptive" if enabled else "disabled"}
    else:
        assert "thinking" not in seen[0]


def test_minimax_wire_extension_preserves_existing_options_and_caller_data(monkeypatch):
    monkeypatch.setattr(GameMasterLLM, "_get_decrypted_key", lambda *_args: "fixture-key")
    client = GameMasterLLM.for_role(
        User(
            llm_settings={
                "small_model_provider": "minimax",
                "small_model": "MiniMax-M3",
                "small_enable_thinking": False,
            }
        ),
        "small",
    )
    existing = {"metadata": {"fixture": True}}
    options = {"extra_body": existing}
    client._apply_thinking_settings(options)
    assert options["extra_body"] == {
        "metadata": {"fixture": True},
        "thinking": {"type": "disabled"},
    }
    assert existing == {"metadata": {"fixture": True}}
