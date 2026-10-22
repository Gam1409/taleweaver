"""Compare Ollama wire formats against a local fake server, without model inference."""

import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Event, Thread
from typing import Any

import pytest
from pydantic import BaseModel

from backend.core.llm_router import GameMasterLLM
from backend.models.user import User


class WireAnswer(BaseModel):
    answer: str


@pytest.fixture
def ollama_server():
    requests: list[tuple[str, dict[str, Any]]] = []
    control = {"delay": 0.0}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args: Any) -> None:
            """Keep the fake server quiet."""

        def do_POST(self) -> None:
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append((self.path, body))
            if self.path != "/api/show" and control["delay"]:
                Event().wait(control["delay"])
            if self.path == "/api/show":
                response = {
                    "model_info": {},
                    "capabilities": ["completion", "tools"],
                    "template": "",
                    "parameters": "",
                }
            else:
                content = '{"answer":"ok"}' if body.get("format") else "ok"
                response = {
                    "model": body["model"],
                    "created_at": "2026-01-01T00:00:00Z",
                    "done": True,
                    "done_reason": "stop",
                    "prompt_eval_count": 10,
                    "eval_count": 5,
                    "total_duration": 1000,
                }
                if self.path == "/api/chat":
                    response["message"] = {"role": "assistant", "content": content}
                else:
                    response["response"] = content
            data = (json.dumps(response) + "\n").encode()
            if body.get("stream") and self.path != "/api/show":
                chunk = dict(response, done=False)
                chunk.pop("done_reason", None)
                final = dict(response)
                if self.path == "/api/chat":
                    final["message"] = {"role": "assistant", "content": ""}
                else:
                    final["response"] = ""
                data = (json.dumps(chunk) + "\n" + json.dumps(final) + "\n").encode()
            self.send_response(200)
            self.send_header(
                "Content-Type", "application/x-ndjson" if body.get("stream") else "application/json"
            )
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            try:
                self.wfile.write(data)
            except BrokenPipeError:
                # A deliberate timeout closes the client before the delayed response.
                return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", requests, control
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@pytest.mark.asyncio
@pytest.mark.parametrize("transport", ["ollama", "ollama_chat"])
async def test_five_router_paths_on_ollama_wire(ollama_server, monkeypatch, transport):
    url, requests, _ = ollama_server
    router = GameMasterLLM.for_role(
        User(
            llm_settings={
                "ollama_api_mode": "chat" if transport == "ollama_chat" else "generate",
                "small_model_provider": "ollama",
                "small_model": "local-test",
                "small_ollama_url": url,
                "small_ollama_num_ctx": 8192,
                "small_max_tokens": 777,
            }
        ),
        "small",
    )
    original = router._apply_ollama_options

    def apply_options(kwargs, model):
        original(kwargs, model)
        kwargs["custom_llm_provider"] = transport

    monkeypatch.setattr(router, "_apply_ollama_options", apply_options)
    assert router.execute_simple_task("system rules", "hello", router.model) == "ok"
    assert await router.aexecute_simple_task("system rules", "hello", router.model) == "ok"
    stream = await router.stream_simple_task(
        "system rules",
        "hello",
        router.model,
        messages=[
            {"role": "system", "content": "system rules"},
            {"role": "user", "content": "first"},
            {"role": "assistant", "content": "prior answer"},
            {"role": "user", "content": "hello"},
        ],
    )
    assert "".join([chunk.choices[0].delta.content or "" async for chunk in stream]) == "ok"
    assert (
        router.execute_complex_task("system rules", "hello", WireAnswer, router.model).answer
        == "ok"
    )
    assert (
        await router.aexecute_complex_task("system rules", "hello", WireAnswer, router.model)
    ).answer == "ok"
    generation = [(path, body) for path, body in requests if path != "/api/show"]
    assert len(generation) == 5
    expected_path = "/api/chat" if transport == "ollama_chat" else "/api/generate"
    for path, body in generation:
        assert path == expected_path
        assert body["options"]["num_ctx"] == 8192
        assert body["options"]["num_predict"] == 777
        assert body["think"] is False
        if transport == "ollama_chat":
            assert body["messages"][0]["role"] == "system"
            assert body["messages"][0]["content"] == "system rules"
        else:
            assert "system rules" in body["prompt"]
    if transport == "ollama_chat":
        assert [message["role"] for message in generation[2][1]["messages"]] == [
            "system",
            "user",
            "assistant",
            "user",
        ]
    for _, body in generation[-2:]:
        assert body["format"]["properties"]["answer"]["type"] == "string"


@pytest.mark.parametrize("transport", ["ollama", "ollama_chat"])
def test_ollama_http_timeout_keeps_four_attempt_policy(ollama_server, monkeypatch, transport):
    """Exercise real HTTP timeouts with subsecond limits; API bounds are tested separately."""
    import litellm

    url, requests, control = ollama_server
    control["delay"] = 0.3
    router = GameMasterLLM.for_role(
        User(
            llm_settings={
                "ollama_api_mode": "chat" if transport == "ollama_chat" else "generate",
                "small_model_provider": "ollama",
                "small_model": "local-test",
                "small_ollama_url": url,
            }
        ),
        "small",
    )
    router.request_timeout = 0.05
    original = router._apply_ollama_options

    def apply_options(kwargs, model):
        original(kwargs, model)
        kwargs["custom_llm_provider"] = transport

    monkeypatch.setattr(router, "_apply_ollama_options", apply_options)
    start = time.monotonic()
    with pytest.raises((litellm.Timeout, litellm.APIConnectionError)):
        router.execute_simple_task("system", "hello", router.model)
    elapsed = time.monotonic() - start
    assert len([path for path, _ in requests if path != "/api/show"]) == 4
    assert 4.5 <= elapsed < 12
