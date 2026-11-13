"""Private bounded failure packets tolerate unsafe content and unavailable disks."""

import asyncio
import json
import os
import re
from uuid import uuid4

import pytest

from backend.core.diagnostic_operations import diagnostic_job
from backend.core.system_diagnostics import service
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


async def test_background_job_opens_its_own_scope_before_parent_turn_ends():
    from backend.core.state_rejection_trace import reject, scope

    enable()
    started = asyncio.Event()
    finish = asyncio.Event()
    session_id = str(uuid4())

    @diagnostic_job("npc_learning")
    async def job(_session_id):
        service.detail("detail.llm.request", text="Independent background request")
        started.set()
        await finish.wait()
        reject("emotion", "unconfirmed", "The background proposal was unconfirmed.")
        return "unchanged result"

    with scope(session_id=session_id, operation="turn"):
        task = asyncio.create_task(job(session_id))
        await asyncio.wait_for(started.wait(), 5)
    finish.set()
    assert await task == "unchanged result"
    assert len(trace_files()) == 1
    assert trace_rows()[0]["context"]["operation"] == "npc_learning"
    assert "Independent background request" in trace_files()[0].read_text()


@pytest.mark.parametrize(
    "exception", [ValueError("Synthetic invalid proposal"), asyncio.CancelledError()]
)
def test_uncaught_failure_or_interruption_is_recorded_and_reraised(exception):
    from backend.core.state_rejection_trace import scope

    enable()
    with pytest.raises(type(exception)) as raised, scope(operation="synthetic_failure"):
        service.detail("detail.llm.request", text="Evidence before failure")
        raise exception
    assert raised.value is exception
    reason = event_payloads(trace_rows(), "state.rejected")[0]
    assert reason["reason_code"] == (
        "operation_interrupted"
        if isinstance(exception, asyncio.CancelledError)
        else "operation_failed"
    )
    assert "Evidence before failure" in trace_files()[0].read_text()


def test_generated_private_filename_and_credentials_are_excluded():
    from backend.core.state_rejection_trace import reject, scope

    enable()
    key = "synthetic-connection-secret"
    bearer = "neutral-bearer-credential"
    with scope(session_id="../must-not-be-a-path", operation="synthetic_validation"):
        service.detail(
            "detail.llm.request",
            request={"api_key": key, "headers": {"Authorization": bearer}, "password": key},
            text=f"api_key={key} Authorization: Bearer {bearer}",
        )
        reject("state", "invalid", "A neutral proposal was rejected.", credentials={"secret": key})
    path = trace_files()[0]
    assert re.fullmatch(r"state-rejection-[a-f0-9]{32}\.jsonl", path.name)
    assert os.stat(path).st_mode & 0o777 == 0o600
    assert key not in path.read_text()
    assert bearer not in path.read_text()
    assert path.parent == service.directory


def test_large_payload_is_whole_and_overflow_is_explicit(monkeypatch):
    from backend.core import state_rejection_trace as traces

    enable()
    text = "Neutral Unicode evidence Ω\n" * 5000
    with traces.scope():
        service.detail("detail.llm.response", response=text)
        traces.reject("state", "invalid", "A neutral proposal was rejected.")
    assert event_payloads(trace_rows(), "detail.llm.response")[0]["response"] == text
    monkeypatch.setattr(traces, "MAX_CAPTURE_BYTES", 1500)
    with traces.scope(operation="bounded_capture"):
        service.detail("detail.llm.response", response=text)
        traces.reject("state", "invalid", "A neutral proposal was rejected.")
    rows = next(trace_rows(path) for path in trace_files() if "bounded_capture" in path.read_text())
    assert event_payloads(rows, "detail.llm.response") == []
    overflow = rows[-1]["capture_overflow"]
    assert overflow["omitted_events"] == 1
    assert overflow["omitted_bytes"] > 1500
    assert overflow["samples"][0]["event"] == "detail.llm.response"
    assert len(overflow["samples"][0]["sha256"]) == 64


def test_retention_bounds_generated_packets_without_deleting_other_logs(monkeypatch):
    from backend.core import state_rejection_storage as storage
    from backend.core.state_rejection_trace import reject

    enable()
    monkeypatch.setattr(storage, "MAX_TRACE_FILES", 2)
    unrelated = service.directory / "keep-other-log.jsonl"
    unrelated.write_text("neutral unrelated log")
    for _ in range(5):
        reject("state", "invalid", "A neutral proposal was rejected.")
    assert len(trace_files()) == 2
    assert unrelated.read_text() == "neutral unrelated log"
    assert any(trace_rows(path)[-1]["retention"]["removed_files"] for path in trace_files())


def test_disk_failure_preserves_gameplay_result_and_publishes_no_partial_packet(monkeypatch):
    from backend.core import state_rejection_storage as storage
    from backend.core.state_rejection_trace import reject, scope

    enable()

    def unavailable(*_args, **_kwargs):
        raise OSError("Synthetic filesystem failure")

    monkeypatch.setattr(storage.os, "replace", unavailable)
    with scope():
        reject("state", "invalid", "A neutral proposal was rejected.")
        result = {"state": "unchanged"}
    assert result == {"state": "unchanged"}
    assert trace_files() == []
    assert list(service.directory.glob(".state-rejection-*.tmp")) == []
    assert service.status()["write_error"] == "Diagnostic storage is unavailable."


def test_unserializable_payload_does_not_break_rejection_or_suppress_domain_exception():
    from backend.core.state_rejection_trace import reject, scope

    enable()
    with pytest.raises(ValueError, match="Original domain error"), scope():
        service.detail("detail.llm.response", response={"bad": float("nan")})
        reject("state", "invalid", "A neutral proposal was rejected.")
        raise ValueError("Original domain error")
    assert len(trace_files()) == 1
    assert "NaN" not in trace_files()[0].read_text()
    assert service.write_failed is True
    json.loads(trace_files()[0].read_text().splitlines()[-1])


def test_overflow_always_retains_a_compact_rejection_cause(monkeypatch):
    from backend.core import state_rejection_trace as traces

    enable()
    monkeypatch.setattr(traces, "MAX_CAPTURE_BYTES", 1)
    with traces.scope():
        service.detail("detail.llm.response", text="Large evidence that cannot fit")
        traces.reject(
            "items", "invalid_target", "The target item does not exist.", proposal={"id": "missing"}
        )
    footer = trace_rows()[-1]
    assert footer["rejection_summaries"][0]["domain"] == "items"
    assert footer["rejection_summaries"][0]["reason_code"] == "invalid_target"
    assert footer["rejection_summaries"][0]["reason"] == "The target item does not exist."
    assert footer["capture_overflow"]["omitted_events"] == 2


async def test_child_scope_overrides_inherited_session_and_turn_in_every_row():
    from backend.core.state_rejection_trace import reject, scope

    enable()
    parent_id, child_id, turn_id = (str(uuid4()) for _ in range(3))

    async def child():
        with scope(session_id=child_id, operation="child_validation"):
            service.detail("detail.llm.request", text="Independent child evidence")
            reject("state", "invalid", "Independent child rejection")

    with (
        service.context(session_id=parent_id, turn_id=turn_id),
        scope(session_id=parent_id, turn_id=turn_id, operation="turn"),
    ):
        await asyncio.create_task(child())
    rows = trace_rows()
    assert rows[0]["context"]["session_id"] == child_id
    assert rows[0]["context"].get("turn_id") is None
    for row in rows[1:-1]:
        assert row["session_id"] == child_id
        assert row.get("turn_id") is None
    assert parent_id not in trace_files()[0].read_text()
    assert turn_id not in trace_files()[0].read_text()


def test_long_unbroken_evidence_and_normal_credential_urls_are_sanitized_losslessly():
    from backend.core.state_rejection_trace import reject, scope

    enable()
    text = "a" * 200_000
    urls = "https://fixture-user:fixture-pass@example.test/path postgres://fixture-user:fixture-pass@example.test/db postgresql+psycopg2://fixture-user:fixture:pass@example.test/db"
    with scope(operation="long_evidence"):
        service.detail("detail.llm.response", text=text, endpoint_urls=urls)
        reject("state", "unconfirmed", "A synthetic proposal was unconfirmed.")
    payload = event_payloads(trace_rows(), "detail.llm.response")[0]
    assert payload["text"] == text
    assert payload["endpoint_urls"].count("[credential excluded]") == 3
    assert "fixture-user" not in payload["endpoint_urls"]
    assert "fixture-pass" not in payload["endpoint_urls"]
