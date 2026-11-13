"""Canonical RAG failures retain packets while ordinary maintenance controls stay quiet."""

import asyncio
import sqlite3
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.exc import DBAPIError, StatementError

from backend.core.inference.registry import InferenceQueueError, InferenceUncertainError
from backend.core.system_diagnostics import service
from backend.engine.memory_rag import maintenance, worker
from backend.engine.memory_rag.scheduling import BackgroundDeferredError
from tests.state_trace_support import (
    event_payloads,
    isolate_trace_directory,
    trace_files,
    trace_rows,
)


@pytest.fixture(autouse=True)
def isolated_trace(tmp_path, monkeypatch):
    yield from isolate_trace_directory(tmp_path, monkeypatch)


def _control(kind):
    return {
        "queue": InferenceQueueError("queue unavailable"),
        "uncertain": InferenceUncertainError("request completion unconfirmed"),
        "deferred": BackgroundDeferredError(),
        "busy": sqlite3.OperationalError("database is locked"),
        "cancelled": asyncio.CancelledError(),
    }[kind]


def _claim():
    return worker.Claim("session", "owner", 3, 7, "synthetic-lease", None, False)


BOUND_SENTINEL = "SYNTHETIC-BOUND-VALUE-MUST-NOT-BE-LOGGED"


def _database_failure(kind):
    statement = "INSERT INTO neutral_values (value) VALUES (?)"
    original = sqlite3.DatabaseError(f"Invalid database value {BOUND_SENTINEL}")
    if kind == "driver":
        return original
    if kind == "dbapi":
        return DBAPIError(statement, (BOUND_SENTINEL,), original)
    failure = StatementError(
        f"Cannot bind {BOUND_SENTINEL}", statement, (BOUND_SENTINEL,), original
    )
    if kind == "wrapped":
        outer = ValueError(f"Database update failed: {failure}")
        outer.__cause__ = failure
        return outer
    return failure


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", maintenance.KINDS)
async def test_failed_rag_phase_keeps_evidence_and_existing_backoff(kind):
    from backend.core.state_rejection_trace import scope

    async def provider():
        service.detail("detail.llm.request", request={"messages": [{"content": "Neutral memory"}]})
        raise ConnectionError("synthetic provider unavailable")

    outcomes = []
    for enabled in (False, True):
        service.set_enabled(True, state_failure_traces=enabled)
        cycle = maintenance.Cycle(cursor=maintenance.KINDS.index(kind))
        jobs = {name: AsyncMock(return_value=False) for name in maintenance.KINDS}
        jobs[kind] = AsyncMock(side_effect=provider)
        with scope(session_id="session", operation="rag_phase"):
            outcomes.append(await cycle.run(jobs))
        assert outcomes[-1].status == "failed"
        assert cycle.failures[kind][0] == 1
        if not enabled:
            assert trace_files() == []
            continue
        assert len(trace_files()) == 1
        with scope(session_id="session", operation="rag_backoff"):
            assert (await cycle.run(jobs)).status == "waiting"
        jobs[kind].assert_awaited_once()
        assert len(trace_files()) == 1
    assert outcomes[0] == outcomes[1]
    rows = trace_rows()
    rejected = event_payloads(rows, "state.rejected")[0]
    assert rejected["domain"] == "memory_rag"
    assert rejected["details"]["proposal"] == {"maintenance_step": kind}
    assert rejected["details"]["failure_reason"] == "synthetic provider unavailable"
    assert (
        event_payloads(rows, "detail.llm.request")[0]["request"]["messages"][0]["content"]
        == "Neutral memory"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error,code",
    [
        (ConnectionError("offline"), "provider"),
        (ValueError("invalid"), "invalid_response"),
        (TimeoutError("expired"), "timeout"),
        (RuntimeError("failed"), "internal"),
    ],
)
async def test_worker_failure_trace_preserves_error_marking_and_false_result(
    monkeypatch, error, code
):
    from backend.core.state_rejection_trace import scope

    claim = _claim()
    monkeypatch.setattr(worker, "_step", AsyncMock(side_effect=error))
    failed = AsyncMock()
    monkeypatch.setattr(worker, "_failed", failed)
    for enabled in (False, True):
        service.set_enabled(True, state_failure_traces=enabled)
        with scope(session_id=claim.session_id, operation="rag_worker"):
            assert await worker._process_claim(claim) is False
        failed.assert_awaited_with(claim, code)
        if not enabled:
            assert trace_files() == []
    assert len(trace_files()) == 1
    rejected = event_payloads(trace_rows(), "state.rejected")[0]
    assert rejected["details"]["proposal"] == {"maintenance_step": "worker_claim"}
    assert rejected["details"]["epoch"] == 3
    assert rejected["details"]["revision"] == 7
    assert rejected["details"]["failure_reason"] == str(error)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["queue", "uncertain", "deferred", "busy", "cancelled"])
async def test_phase_control_errors_propagate_without_becoming_rag_failures(kind):
    from backend.core.state_rejection_trace import scope

    service.set_enabled(True, state_failure_traces=True)
    error = _control(kind)
    cycle = maintenance.Cycle()
    jobs = {name: AsyncMock(side_effect=error) for name in maintenance.KINDS}
    with scope(session_id="session", operation="rag_control"), pytest.raises(type(error)):
        await cycle.run(jobs)
    assert cycle.failures == {} and cycle.errors == {}
    assert trace_files() == []


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["queue", "uncertain", "deferred", "busy", "cancelled"])
async def test_worker_controls_keep_release_and_retry_semantics_without_failure_packet(
    monkeypatch, kind
):
    from backend.core.state_rejection_trace import scope

    service.set_enabled(True, state_failure_traces=True)
    claim = _claim()
    monkeypatch.setattr(worker, "_step", AsyncMock(side_effect=_control(kind)))
    released, failed = AsyncMock(), AsyncMock()
    monkeypatch.setattr(worker, "_release", released)
    monkeypatch.setattr(worker, "_failed", failed)
    with scope(session_id=claim.session_id, operation="rag_control"):
        if kind == "cancelled":
            with pytest.raises(asyncio.CancelledError):
                await worker._process_claim(claim)
        else:
            assert await worker._process_claim(claim) is (kind in {"deferred", "busy"})
    released.assert_awaited_once()
    failed.assert_not_awaited()
    assert trace_files() == []


@pytest.mark.asyncio
async def test_idle_and_successful_rag_work_emit_no_failure_packet(monkeypatch):
    from backend.core.state_rejection_trace import scope

    service.set_enabled(True, state_failure_traces=True)
    jobs = {name: AsyncMock(return_value=False) for name in maintenance.KINDS}
    with scope(session_id="session", operation="rag_idle"):
        assert (await maintenance.Cycle().run(jobs)).status == "ready"
    monkeypatch.setattr(worker, "_step", AsyncMock(return_value=True))
    with scope(session_id="session", operation="rag_success"):
        assert await worker._process_claim(_claim()) is True
    assert trace_files() == []


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["statement", "dbapi", "driver", "wrapped"])
@pytest.mark.parametrize("stage", ["phase", "worker"])
async def test_database_failures_never_copy_sql_or_bound_values_into_rejection_packets(
    monkeypatch, kind, stage
):
    from backend.core.state_rejection_trace import scope

    service.set_enabled(True, state_failure_traces=True)
    error = _database_failure(kind)
    with scope(session_id="session", operation="database_failure"):
        if stage == "phase":
            jobs = {name: AsyncMock(side_effect=error) for name in maintenance.KINDS}
            assert (await maintenance.Cycle().run(jobs)).status == "failed"
        else:
            monkeypatch.setattr(worker, "_step", AsyncMock(side_effect=error))
            failed = AsyncMock()
            monkeypatch.setattr(worker, "_failed", failed)
            assert await worker._process_claim(_claim()) is False
            failed.assert_awaited_once()
    assert len(trace_files()) == 1
    packet = trace_files()[0].read_text()
    assert BOUND_SENTINEL not in packet
    assert "INSERT INTO neutral_values" not in packet
    details = event_payloads(trace_rows(), "state.rejected")[0]["details"]
    assert details["error"]["type"] == type(error).__name__
    assert "failure_args" not in details and "failure_reason" not in details
