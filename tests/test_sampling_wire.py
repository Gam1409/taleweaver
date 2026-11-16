"""Compatible sampler extensions traverse LiteLLM and the OpenAI SDK as request fields."""

import json

import httpx
from pydantic import BaseModel

from backend.core import custom_openai
from backend.core.llm_router import GameMasterLLM
from backend.models.user import User
from tests.test_custom_openai import local_policy

__all__ = ["local_policy"]


class Answer(BaseModel):
    answer: str


async def test_compatible_sampling_reaches_text_json_and_stream_requests(monkeypatch, local_policy):
    captured = []
    original = httpx.AsyncClient

    def respond(request):
        body = json.loads(request.content)
        captured.append(body)
        if not body.get("stream"):
            return httpx.Response(
                200,
                json={
                    "id": "test",
                    "created": 1,
                    "object": "chat.completion",
                    "model": "local",
                    "choices": [
                        {
                            "index": 0,
                            "message": {"role": "assistant", "content": '{"answer":"ok"}'},
                            "finish_reason": "stop",
                        }
                    ],
                },
            )
        chunks = [
            {
                "id": "test",
                "created": 1,
                "object": "chat.completion.chunk",
                "model": "local",
                "choices": [{"index": 0, "delta": {"content": "ok"}, "finish_reason": None}],
            },
            {
                "id": "test",
                "created": 1,
                "object": "chat.completion.chunk",
                "model": "local",
                "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
            },
        ]
        content = (
            "".join("data: " + json.dumps(chunk) + "\n\n" for chunk in chunks) + "data: [DONE]\n\n"
        )
        return httpx.Response(200, content=content, headers={"content-type": "text/event-stream"})

    class Client(original):
        def __init__(self, **kwargs):
            super().__init__(transport=httpx.MockTransport(respond), **kwargs)

    monkeypatch.setattr(custom_openai.httpx, "AsyncClient", Client)
    user = User(
        llm_settings={
            "complex_model_provider": "custom_openai",
            "complex_model": "local",
            "custom_openai_url": "http://127.0.0.1:8080/v1",
            "sampling": {
                "defaults": {
                    "temperature": 0.95,
                    "top_p": 0.97,
                    "top_k": 50,
                    "min_p": 0.06,
                    "repetition_penalty": 1.08,
                    "local_extensions": True,
                }
            },
        },
        encrypted_api_keys={},
    )
    router = GameMasterLLM.for_role(user, "complex")
    assert await router.aexecute_simple_task("system", "hello", router.model) == '{"answer":"ok"}'
    assert (
        await router.aexecute_complex_task("system", "hello", Answer, router.model)
    ).answer == "ok"
    stream = await router.stream_simple_task("system", "hello", router.model)
    assert "".join([chunk.choices[0].delta.content or "" async for chunk in stream]) == "ok"
    assert len(captured) == 3
    for body in captured:
        assert {
            key: body.get(key)
            for key in ("temperature", "top_p", "top_k", "min_p", "repetition_penalty")
        } == {
            "temperature": 0.95,
            "top_p": 0.97,
            "top_k": 50,
            "min_p": 0.06,
            "repetition_penalty": 1.08,
        }
        assert "extra_body" not in body
