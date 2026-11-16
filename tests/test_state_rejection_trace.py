"""Rejection-only full traces are opt-in, lossless, isolated and observational."""

import asyncio
from types import SimpleNamespace
from uuid import uuid4

import pytest

from backend.core.engine_detailed_trace import step, turn_context
from backend.core.llm_detailed_trace import trace_async
from backend.core.system_diagnostics import DiagnosticService, service
from tests.state_trace_support import (
    event_payloads,
    isolate_trace_directory,
    trace_files,
    trace_rows,
)


@pytest.fixture(autouse=True)
def isolated_diagnostics(tmp_path, monkeypatch):
    yield from isolate_trace_directory(tmp_path, monkeypatch)


def enable():
    service.set_enabled(True, state_failure_traces=True)


def test_new_flag_defaults_off_and_survives_restart_independently():
    assert service.status()["state_failure_traces"] is False
    assert service.capture_token() is None
    enable()
    assert service.detail_token() is None
    assert service.capture_token() is not None
    service.close()
    restarted = DiagnosticService(service.directory)
    restarted.initialize()
    try:
        assert restarted.state_failure_traces is True
        assert restarted.detailed_logging is False
    finally:
        restarted.close()


def test_successful_scope_writes_no_rejection_file_and_no_full_main_log():
    from backend.core.state_rejection_trace import scope

    enable()
    with scope(session_id=str(uuid4()), operation="successful_check"):
        service.detail("detail.engine.completed", state={"text": "Neutral full payload"})
    assert trace_files() == []
    assert "Neutral full payload" not in (service.directory / "system-debug.jsonl").read_text()


def test_disabled_master_forces_both_subordinate_flags_off():
    service.set_enabled(False, detailed_logging=True, state_failure_traces=True)
    assert service.status()["state_failure_traces"] is False
    assert service.detail_token() is None
    assert service.capture_token() is None


async def test_rejection_scope_collects_actual_engine_and_full_wire_events():
    from backend.core.state_rejection_trace import reject

    enable()
    manager = SimpleNamespace(
        game_id=str(uuid4()), turn_id=str(uuid4()), state=SimpleNamespace(inventory=[])
    )
    text = "Neutral Unicode scene Ω\n" * 5000

    @trace_async
    async def transport(_router, _kwargs):
        return {"choices": [{"message": {"content": text}}]}

    @step("synthetic.state.validation")
    async def operation(owner, payload):
        await transport(
            SimpleNamespace(provider="custom_openai"),
            {"messages": [{"role": "user", "content": text}], "response_format": payload},
        )
        reject(
            "items", "proposal_rejected", "The referenced item is unavailable.", proposal=payload
        )
        return {"accepted": False}

    with turn_context(manager, ("Neutral player action",), {}):
        result = await operation(manager, {"type": "json_schema", "schema": {"field": "item"}})
    assert result == {"accepted": False}
    assert len(trace_files()) == 1
    rows = trace_rows()
    assert rows[0]["context"]["session_id"] == manager.game_id
    assert rows[-1]["rejected_count"] == 1
    request = event_payloads(rows, "detail.llm.request")[0]
    assert request["request"]["messages"][0]["content"] == text
    assert request["request"]["response_format"]["schema"] == {"field": "item"}
    response = event_payloads(rows, "detail.llm.response")[0]
    assert response["response"]["choices"][0]["message"]["content"] == text
    assert event_payloads(rows, "state.rejected")[0]["reason_code"] == "proposal_rejected"
    assert event_payloads(rows, "detail.engine.completed")[0]["result"] == result
    assert "Neutral player action" not in (service.directory / "system-debug.jsonl").read_text()


async def test_stream_capture_keeps_all_chunks_when_detailed_logging_is_off():
    from backend.core.state_rejection_trace import reject, scope

    enable()

    async def chunks():
        for index in range(12):
            yield {"choices": [{"delta": {"content": f"chunk-{index}:" + "x" * 800}}]}

    @trace_async
    async def transport(_router, _kwargs):
        return chunks()

    with scope(operation="stream_validation"):
        stream = await transport(SimpleNamespace(provider="custom_openai"), {"stream": True})
        actual = [chunk async for chunk in stream]
        reject("state", "incomplete_contract", "The state proposal is unconfirmed.")
    payloads = event_payloads(trace_rows(), "detail.llm.stream")
    captured = [chunk for batch in payloads for chunk in batch["chunks"]]
    assert len(captured) == len(actual)
    assert [chunk["choices"][0]["message"]["content"] for chunk in captured] == [
        chunk["choices"][0]["delta"]["content"] for chunk in actual
    ]


@pytest.mark.parametrize("disable_master", [False, True])
def test_disabling_and_reenabling_does_not_revive_an_old_scope(disable_master):
    from backend.core.state_rejection_trace import reject, scope

    enable()
    with scope(operation="obsolete_epoch"):
        service.detail("detail.llm.request", text="Discarded old request")
        reject("state", "pending_rejection", "This scope is superseded.")
        service.set_enabled(not disable_master)
        enable()
        service.detail("detail.llm.response", text="Discarded late response")
        reject("state", "late_rejection", "This old scope must stay inactive.")
    assert trace_files() == []
    with scope(operation="fresh_epoch"):
        reject("state", "fresh_rejection", "A fresh scope remains enabled.")
    assert len(trace_files()) == 1
    assert "Discarded" not in trace_files()[0].read_text()


async def test_concurrent_sessions_have_independent_complete_packets():
    from backend.core.state_rejection_trace import reject, scope

    enable()
    arrived = 0
    gate = asyncio.Event()
    sessions = [str(uuid4()), str(uuid4())]

    async def operation(session_id):
        nonlocal arrived
        with scope(session_id=session_id, operation="parallel_validation"):
            service.detail("detail.llm.request", text=f"request-{session_id}")
            arrived += 1
            if arrived == 2:
                gate.set()
            await asyncio.wait_for(gate.wait(), 5)
            reject("movement", "unconfirmed", f"reason-{session_id}")
            service.detail("detail.llm.response", text=f"response-{session_id}")

    await asyncio.gather(*(operation(session_id) for session_id in sessions))
    assert len(trace_files()) == 2
    for path in trace_files():
        rows = trace_rows(path)
        session_id = rows[0]["context"]["session_id"]
        other = next(item for item in sessions if item != session_id)
        assert f"request-{session_id}" in path.read_text()
        assert f"response-{session_id}" in path.read_text()
        assert other not in path.read_text()


async def test_background_task_cannot_append_to_or_flush_a_closed_inherited_scope():
    from backend.core.state_rejection_trace import reject, scope

    enable()
    gate = asyncio.Event()

    async def late_work():
        await gate.wait()
        service.detail("detail.llm.response", text="Late inherited response")
        reject("state", "late", "No standalone packet from an ended inherited scope.")

    with scope(operation="completed_parent"):
        task = asyncio.create_task(late_work())
    gate.set()
    await task
    assert trace_files() == []


def test_standalone_rejection_and_nested_scope_keep_reasons_and_safe_context():
    from backend.core.state_rejection_trace import reject, scope

    enable()
    session_id = str(uuid4())
    with service.context(session_id=session_id):
        reject("emotion", "unsupported", "The emotion proposal lacks evidence.")
    assert trace_rows()[0]["context"]["session_id"] == session_id
    with (
        scope(session_id=session_id, operation="outer"),
        scope(session_id=session_id, operation="inner"),
    ):
        reject("physical", "unsupported", "The physical proposal lacks evidence.")
    assert len(trace_files()) == 2


def test_observation_does_not_suppress_domain_errors():
    from backend.core.state_rejection_trace import reject, scope

    enable()
    with pytest.raises(ValueError, match="Synthetic validation failure"), scope():
        reject("state", "invalid", "The proposal was rejected.")
        raise ValueError("Synthetic validation failure")
    assert len(trace_files()) == 1


def test_both_flags_keep_existing_main_detail_semantics():
    from backend.core.state_rejection_trace import reject, scope

    service.set_enabled(True, detailed_logging=True, state_failure_traces=True)
    assert service.detail_token() == service.capture_token()
    with scope():
        service.detail("detail.engine.completed", text="Visible in both selected logs")
        reject("state", "invalid", "A synthetic proposal was rejected.")
    assert "Visible in both selected logs" in trace_files()[0].read_text()
    assert "Visible in both selected logs" in (service.directory / "system-debug.jsonl").read_text()


def test_capture_snapshots_mutable_payloads_and_off_does_not_serialize():
    from backend.core.state_rejection_trace import reject, scope

    class MustNotSerialize:
        def model_dump(self, **_kwargs):
            raise AssertionError("Disabled diagnostics must not serialize")

    with scope():
        reject("state", "invalid", "Disabled observation", payload=MustNotSerialize())
    assert not service.directory.exists()
    enable()
    payload = {"items": ["original fixture item"]}
    with scope():
        service.detail("detail.engine.started", proposal=payload)
        reject("items", "invalid", "The proposal is rejected.", proposal=payload)
        payload["items"].append("later mutation")
    rows = trace_rows()
    assert event_payloads(rows, "detail.engine.started")[0]["proposal"] == {
        "items": ["original fixture item"]
    }
    assert event_payloads(rows, "state.rejected")[0]["details"]["proposal"] == {
        "items": ["original fixture item"]
    }
    assert rows[0]["schema_version"] == 1
    assert rows[0]["app_version"] and rows[0]["python_version"]
