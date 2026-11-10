"""Full payloads require an explicit flag and must never change execution or stream ownership."""

import json
import logging
from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from backend.core import custom_openai
from backend.core.llm_detailed_trace import trace_async
from backend.core.system_diagnostics import DiagnosticService, service
from backend.engine.chpm.state import load
from backend.models.chat import ChatMessage
from tests import test_custom_openai as endpoint_fixtures
from tests.conftest import TestSessionLocal
from tests.emotional_scene_fixture import BEATS, seed_emotional_scene
from tests.test_chpm_local_failure_turn import install, play
from tests.test_emotional_scene import EmotionalRoles
from tests.test_narrative_fidelity import response

local_policy = endpoint_fixtures.local_policy
TEXT = "Лина: [crying] «Ах… <sigh><sigh><sigh> Не молчи!»\n" * 400
KEY = "connection-secret-do-not-record"


@pytest.fixture(autouse=True)
def diagnostic_directory(tmp_path, monkeypatch):
    service.close()
    monkeypatch.setattr(service, "directory", tmp_path / "log")
    service.write_failed = False
    yield
    service.close()


def records():
    path = service.directory / "system-debug.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_detailed_payloads_are_absent_by_default_and_survive_restart_only_when_selected():
    service.set_enabled(True)
    service.detail("detail.engine.event", text=TEXT)
    assert TEXT not in str(records())
    service.set_enabled(True, detailed_logging=True)
    service.detail("detail.engine.event", text=TEXT, api_key=KEY, headers={"Authorization": KEY})
    assert any(row.get("detail", {}).get("text") == TEXT for row in records())
    assert KEY not in str(records())
    service.close()
    restarted = DiagnosticService(service.directory)
    restarted.initialize()
    try:
        assert restarted.enabled and restarted.detailed_logging
    finally:
        restarted.close()
    service.set_enabled(True)
    assert not service.detailed_logging


def test_large_unicode_payloads_are_lossless_multipart_records():
    service.set_enabled(True, detailed_logging=True)
    text = TEXT * 8
    service.detail("detail.llm.response", response=text)
    parts = [row for row in records() if row["event"] == "detail.llm.response"]
    assert len(parts) > 1
    assert [row["part"] for row in parts] == list(range(1, len(parts) + 1))
    assert json.loads("".join(row["payload_json_part"] for row in parts))["response"] == text
    assert all(row["parts"] == len(parts) for row in parts)


@pytest.mark.usefixtures("local_policy")
async def test_invalid_model_json_is_recorded_before_parsing_without_connection_secrets(
    monkeypatch,
):
    router = endpoint_fixtures.make_router(KEY)
    service.set_enabled(True, detailed_logging=True)
    calls = []

    async def completion(_router, kwargs):
        calls.append(kwargs)
        result = response('{"broken":')
        result.choices[0].finish_reason = "stop"
        return result

    monkeypatch.setattr(custom_openai, "acomplete", completion)

    class Answer(BaseModel):
        answer: str

    with pytest.raises(ValueError):
        await router.aexecute_complex_task("Full system instruction", TEXT, Answer, "test-model")
    assert len(calls) == 1
    rows = records()
    request = next(row["detail"] for row in rows if row["event"] == "detail.llm.request")
    result = next(row["detail"] for row in rows if row["event"] == "detail.llm.response")
    assert any(TEXT in message.get("content", "") for message in request["request"]["messages"])
    assert result["response"]["choices"][0]["message"]["content"] == '{"broken":'
    assert KEY not in str(rows)
    assert next(row["call_id"] for row in rows if row["event"] == "detail.llm.request")


@pytest.mark.parametrize("ending", ["complete", "failure", "close", "disable", "toggle"])
async def test_stream_records_partial_output_and_preserves_close_and_error(ending):
    service.set_enabled(True, detailed_logging=True)
    closed = []

    async def chunks():
        try:
            yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="Ах…"))])
            if ending == "failure":
                raise ConnectionError("provider disconnected")
            yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=" Ещё…"))])
        finally:
            closed.append(True)

    @trace_async
    async def transport(router, kwargs):
        return chunks()

    stream = await transport(
        SimpleNamespace(provider="custom_openai"), {"stream": True, "messages": []}
    )
    first = await anext(stream)
    assert first.choices[0].delta.content == "Ах…"
    if ending in {"disable", "toggle"}:
        service.set_enabled(True)
        if ending == "toggle":
            service.set_enabled(True, detailed_logging=True)
        assert [chunk async for chunk in stream]
    elif ending == "close":
        await stream.aclose()
    elif ending == "failure":
        with pytest.raises(ConnectionError):
            await anext(stream)
    else:
        assert [chunk async for chunk in stream]
    assert closed == [True]
    content = str(records())
    assert ("Ах…" in content) == (ending not in {"disable", "toggle"})
    assert "provider disconnected" not in content


async def test_embedding_inputs_vectors_and_http_body_are_visible_only_in_detailed_mode(
    monkeypatch,
):
    import httpx

    from backend.engine.memory_rag import embeddings
    from backend.engine.memory_rag.settings import MemoryRagSettings

    settings = MemoryRagSettings(
        enabled=True, base_url="https://example.com", model="embedding-model"
    )
    monkeypatch.setattr(embeddings, "validate_embedding_url", lambda _: "https://example.com")

    async def post(*_args):
        return httpx.Response(
            200,
            json={"data": [{"index": 0, "embedding": [0.1, 0.2]}]},
            request=httpx.Request("POST", "https://example.com/v1/embeddings"),
        )

    monkeypatch.setattr(embeddings, "_post", post)
    service.set_enabled(True)
    await embeddings.embed_with_settings(settings, [TEXT[:1000]], api_key=KEY)
    assert "Ах…" not in str(records())
    service.set_enabled(True, detailed_logging=True)
    assert await embeddings.embed_with_settings(settings, [TEXT[:1000]], api_key=KEY) == [
        [0.1, 0.2]
    ]
    rows = records()
    assert "Ах…" in str(rows) and "embedding-model" in str(rows)
    assert any(row["event"] == "detail.embedding.http.response" for row in rows)
    assert next(
        row["detail"]["result"] for row in rows if row["event"] == "detail.embedding.response"
    ) == [[0.1, 0.2]]
    assert KEY not in str(rows)


@pytest.mark.usefixtures("local_policy")
async def test_full_turn_records_controls_cues_and_state_without_altering_emotional_text(
    monkeypatch,
):
    service.set_enabled(True, detailed_logging=True)
    roles = EmotionalRoles(7, True)
    install(monkeypatch, roles)
    async with TestSessionLocal() as db:
        user, _ = await seed_emotional_scene(db)
        host, _ = await play(db, user, BEATS[0].action)
        reply = await db.get(ChatMessage, load(host.state).actors["LINA"].reply_id)
        assert reply.content == BEATS[0].body
    rows = records()
    steps = {row.get("detail", {}).get("step") for row in rows}
    assert {
        "npc.prepare",
        "npc.perception",
        "narration.review",
        "narration.repair",
        "items.scene.conditions.reconcile",
    } <= steps
    assert any(
        row["event"] == "detail.engine.event" and row["detail"]["event_name"] == "final"
        for row in rows
    )
    assert not service.write_failed


async def test_administrator_must_explicitly_save_detailed_logging(auth_client):
    result = await auth_client.put(
        "/api/system-diagnostics",
        json={
            "enabled": True,
            "detailed_logging": True,
        },
    )
    assert result.status_code == 200 and result.json()["detailed_logging"] is True
    assert (await auth_client.get("/api/system-diagnostics")).json()["detailed_logging"] is True
    assert (
        await auth_client.put(
            "/api/system-diagnostics",
            json={
                "enabled": True,
                "detailed_logging": "true",
            },
        )
    ).status_code == 422
    result = await auth_client.put("/api/system-diagnostics", json={"enabled": True})
    assert result.status_code == 200 and result.json()["detailed_logging"] is False
    result = await auth_client.put(
        "/api/system-diagnostics", json={"enabled": False, "detailed_logging": True}
    )
    assert result.status_code == 200 and result.json()["detailed_logging"] is False


async def test_unconsumed_stream_is_closed_immediately_and_only_once():
    service.set_enabled(True, detailed_logging=True)
    closes = []

    class Source:
        def __aiter__(self):
            return self

        async def __anext__(self):
            raise AssertionError("The probe must not consume or request model output")

        async def aclose(self):
            closes.append(True)

    @trace_async
    async def transport(router, kwargs):
        return Source()

    stream = await transport(SimpleNamespace(provider="custom_openai"), {"stream": True})
    await stream.aclose()
    await stream.aclose()
    assert closes == [True]


def test_operational_messages_redact_credentials_and_bad_formatting_does_not_raise():
    service.set_enabled(True, detailed_logging=True)
    record = logging.LogRecord(
        "backend.engine.example",
        logging.WARNING,
        __file__,
        1,
        "api_key=%s reaction=%s",
        (KEY, "Ах…"),
        None,
    )
    service._capture.emit(record)
    content = str(records())
    assert KEY not in content and "Ах…" in content
    invalid = logging.LogRecord(
        "backend.engine.example", logging.WARNING, __file__, 1, "%s %s", ("one argument",), None
    )
    service._capture.emit(invalid)
    assert "Message unavailable: TypeError" in str(records())
