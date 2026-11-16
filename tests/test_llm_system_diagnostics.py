"""LLM diagnostic hooks carry lifecycle metadata, never conversation payloads."""

import asyncio
from types import SimpleNamespace
from uuid import uuid4

import pytest

from backend.core import llm_diagnostics, llm_logger

SECRET = "PRIVATE_STORY_API_KEY_SENTINEL"
ROUTER = SimpleNamespace(provider="custom_openai", model_category="small")


@pytest.fixture
def events(monkeypatch):
    records = []
    monkeypatch.setattr(
        llm_diagnostics, "emit", lambda event, **fields: records.append((event, fields))
    )
    return records


def test_bridge_is_active_without_raw_telemetry_and_drops_private_fields(events, monkeypatch):
    monkeypatch.setattr(llm_logger, "_TELEMETRY_ENABLED", False)
    identifier = str(uuid4())
    llm_logger.log_structured_event(
        "gm.turn.memory_recall",
        game_id=identifier,
        source_ids=[SECRET],
        metadata={"prompt": SECRET},
        audience=SECRET,
        model=SECRET,
        provider="custom_openai",
        duration_ms=12.3,
        chars=42,
    )
    llm_logger.log_llm_interaction(
        SECRET,
        "custom_openai",
        SECRET,
        SECRET,
        SECRET,
        {"content": SECRET, "usage": {"prompt_tokens": 12, "completion_tokens": SECRET}},
        game_id=identifier,
        metadata={"secret": SECRET},
    )
    assert len(events) == 2
    assert SECRET not in str(events)
    assert events[0][1] == {
        "game_id": identifier,
        "provider": "custom_openai",
        "duration_ms": 12.3,
        "chars": 42,
    }
    assert events[1][1]["prompt_tokens"] == 12


def test_bridge_rejects_untrusted_event_provider_and_identifier(events):
    llm_diagnostics.bridge_event(SECRET, {"provider": "openai"})
    llm_diagnostics.bridge_event(
        "gm.turn.request", {"provider": SECRET, "game_id": SECRET, "duration_ms": float("nan")}
    )
    assert events == [("gm.turn.request", {})]


async def test_async_success_is_correlated_without_arguments_or_result(events):
    @llm_diagnostics.async_call("structured")
    async def operation(router, prompt, **kwargs):
        return {"response": SECRET}

    assert await operation(ROUTER, SECRET, game_id=str(uuid4()), metadata={"text": SECRET}) == {
        "response": SECRET
    }
    assert [event for event, _ in events] == ["llm.started", "llm.completed"]
    assert events[0][1]["call_id"] == events[1][1]["call_id"]
    assert events[1][1]["duration_ms"] >= 0
    assert SECRET not in str(events)


@pytest.mark.parametrize("error", [RuntimeError(SECRET), asyncio.CancelledError(SECRET)])
async def test_async_errors_preserve_exception_identity_for_safe_serializer(events, error):
    @llm_diagnostics.async_call("structured")
    async def operation(router, prompt):
        raise error

    with pytest.raises(type(error)) as raised:
        await operation(ROUTER, SECRET)
    assert raised.value is error
    expected = "llm.cancelled" if isinstance(error, asyncio.CancelledError) else "llm.failed"
    assert events[-1][0] == expected
    assert events[-1][1]["error"] is error
    assert SECRET not in str({k: v for k, v in events[-1][1].items() if k != "error"})


@pytest.mark.parametrize("failure", [False, True])
def test_sync_lifecycle_retains_behavior(events, failure):
    @llm_diagnostics.sync_call("simple")
    def operation(router, prompt):
        if failure:
            raise ValueError(SECRET)
        return SECRET

    if failure:
        with pytest.raises(ValueError):
            operation(ROUTER, SECRET)
    else:
        assert operation(ROUTER, SECRET) == SECRET
    assert events[-1][0] == ("llm.failed" if failure else "llm.completed")


@pytest.mark.parametrize("ending", ["normal", "failure", "close"])
async def test_stream_lifecycle_tracks_consumption_and_closes_source(events, ending):
    closed = False

    async def source():
        nonlocal closed
        try:
            yield SECRET
            if ending == "failure":
                raise ConnectionError(SECRET)
            yield SECRET
        finally:
            closed = True

    @llm_diagnostics.async_call("stream")
    async def operation(router, prompt):
        return source()

    stream = await operation(ROUTER, SECRET)
    assert [event for event, _ in events] == ["llm.started"]
    assert await anext(stream) == SECRET
    if ending == "close":
        await stream.aclose()
    elif ending == "failure":
        with pytest.raises(ConnectionError):
            await anext(stream)
    else:
        assert [chunk async for chunk in stream] == [SECRET]
    assert closed
    assert (
        events[-1][0]
        == {"normal": "llm.completed", "failure": "llm.failed", "close": "llm.cancelled"}[ending]
    )


@pytest.mark.parametrize("kind", ["embedding", "image"])
@pytest.mark.parametrize("ending", ["success", "failure", "cancelled"])
async def test_provider_operation_lifecycle(events, kind, ending):
    @llm_diagnostics.async_operation(kind)
    async def operation(prompt, provider="comfyui", texts=None, **kwargs):
        if ending == "failure":
            raise RuntimeError(SECRET)
        if ending == "cancelled":
            raise asyncio.CancelledError(SECRET)
        return SECRET

    if ending == "success":
        assert await operation(SECRET, texts=[SECRET], model=SECRET) == SECRET
    else:
        error = RuntimeError if ending == "failure" else asyncio.CancelledError
        with pytest.raises(error):
            await operation(SECRET, texts=[SECRET], model=SECRET)
    suffix = {"success": "completed", "failure": "failed", "cancelled": "cancelled"}[ending]
    assert [event for event, _ in events] == [f"{kind}.started", f"{kind}.{suffix}"]
    assert events[0][1]["call_id"] == events[1][1]["call_id"]
    assert SECRET not in str(events[0])


async def test_real_embedding_and_image_entrypoints_emit_metadata(events, monkeypatch):
    from backend.engine import comfyui_images
    from backend.engine.media_engine import MediaEngine
    from backend.engine.memory_rag import embeddings
    from backend.engine.memory_rag.settings import MemoryRagSettings

    async def embed(*args):
        return [[0.1, 0.2]]

    async def image(*args):
        return SECRET

    monkeypatch.setattr(embeddings, "_embed", embed)
    monkeypatch.setattr(comfyui_images, "generate_comfy_image", image)
    config = MemoryRagSettings(enabled=True, base_url="http://localhost:1234", model=SECRET)
    assert await embeddings.embed_with_settings(config, [SECRET], api_key=SECRET) == [[0.1, 0.2]]
    assert (
        await MediaEngine.generate_image(
            SECRET, SECRET, SECRET, provider="comfyui", provider_options={"private": SECRET}
        )
        == SECRET
    )
    assert [event for event, _ in events] == [
        "embedding.started",
        "embedding.completed",
        "image.started",
        "image.completed",
    ]
    assert events[0][1]["count"] == 1
    assert events[2][1]["provider"] == "comfyui"
    assert SECRET not in str(events)


async def test_real_diagnostic_writer_never_serializes_provider_payloads(tmp_path, monkeypatch):
    import json

    from backend.core import system_diagnostics

    diagnostic = system_diagnostics.DiagnosticService(tmp_path / "log")
    monkeypatch.setattr(system_diagnostics, "service", diagnostic)

    @llm_diagnostics.async_call("structured")
    async def operation(router, prompt, **kwargs):
        raise RuntimeError(SECRET)

    try:
        diagnostic.set_enabled(True, persist=False)
        with pytest.raises(RuntimeError):
            await operation(ROUTER, SECRET, api_key=SECRET, endpoint=SECRET)
    finally:
        diagnostic.close()
    contents = (tmp_path / "log" / "system-debug.jsonl").read_text()
    assert SECRET not in contents
    records = [json.loads(line) for line in contents.splitlines()]
    failure = next(record for record in records if record["event"] == "llm.failed")
    assert "RuntimeError" in str(failure)
    assert "duration_ms" in failure


async def test_purpose_phase_are_allowlisted_for_calls_and_bridge(events):
    @llm_diagnostics.async_call("structured")
    async def operation(router, **kwargs):
        return SECRET

    await operation(ROUTER, operation="generate_world", phase="mechanics")
    assert events[-1][1]["purpose"] == "generate_world"
    assert events[-1][1]["phase"] == "mechanics"
    llm_diagnostics.bridge_event("gm.turn.request", {"operation": SECRET, "phase": SECRET})
    assert SECRET not in str(events)


def test_retry_only_forwards_delay_attempt_provider_and_exception(events):
    error = TimeoutError(SECRET)
    llm_diagnostics.retry(ROUTER, 2, 1.5, error)
    assert events == [
        ("llm.retry", {"attempt": 2, "delay_ms": 1500, "provider": "custom_openai", "error": error})
    ]


async def test_image_empty_result_is_failure_without_changing_return_value(events):
    @llm_diagnostics.async_operation("image")
    async def operation(prompt):
        return None

    assert await operation(SECRET) is None
    assert events[-1][0] == "image.failed"
