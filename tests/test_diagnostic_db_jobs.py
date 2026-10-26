"""Technical instrumentation must not collect SQL or background-job payloads."""

import asyncio
from contextlib import contextmanager
from contextvars import ContextVar
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError

from backend.core import diagnostic_db, diagnostic_operations

PRIVATE = "private-player-text-and-provider-key"


class RecordingService:
    enabled = True

    def __init__(self):
        self.events = []
        self.active = ContextVar("diagnostic_test_context", default=None)
        self.active.set({})

    @contextmanager
    def context(self, **fields):
        token = self.active.set({**self.active.get(), **fields})
        try:
            yield
        finally:
            self.active.reset(token)

    def emit(self, name, **fields):
        if self.enabled:
            self.events.append((name, {**self.active.get(), **fields}))


@pytest.fixture
async def diagnostics(monkeypatch):
    service = RecordingService()
    monkeypatch.setattr(diagnostic_db, "_service", lambda: service)
    monkeypatch.setattr(diagnostic_operations, "_service", lambda: service)
    return service


async def test_sql_diagnostics_exclude_query_values_and_install_once(diagnostics):
    engine = create_engine("sqlite://")
    diagnostic_db.install_diagnostics(engine)
    diagnostic_db.install_diagnostics(engine)
    try:
        with engine.begin() as connection:
            assert connection.scalar(text("SELECT :value"), {"value": PRIVATE}) == PRIVATE
        with engine.connect() as connection, pytest.raises(OperationalError):
            connection.execute(text("SELECT * FROM private_player_text_and_provider_key"))
        queries = [fields for name, fields in diagnostics.events if name == "db.query"]
        assert len(queries) == 1
        assert queries[0]["operation"] == "SELECT"
        assert queries[0]["duration_ms"] >= 0
        assert {
            fields["operation"] for name, fields in diagnostics.events if name == "db.transaction"
        } == {"BEGIN", "COMMIT", "ROLLBACK"}
        errors = [fields for name, fields in diagnostics.events if name == "db.error"]
        assert len(errors) == 1
        assert set(errors[0]) == {"error", "operation", "duration_ms"}
        # The service receives the exception for safe class/frame extraction, never its text.
        for _name, fields in diagnostics.events:
            assert set(fields) <= {"error", "operation", "duration_ms"}
            assert PRIVATE not in str(
                {key: value for key, value in fields.items() if key != "error"}
            )
    finally:
        engine.dispose()


async def test_disabled_sql_diagnostics_leave_behavior_unchanged(diagnostics):
    diagnostics.enabled = False
    engine = create_engine("sqlite://")
    diagnostic_db.install_diagnostics(engine)
    try:
        with engine.begin() as connection:
            assert connection.scalar(text("SELECT :value"), {"value": PRIVATE}) == PRIVATE
        assert diagnostics.events == []
    finally:
        engine.dispose()


async def test_job_returns_private_result_without_recording_payload(diagnostics):
    identifier = str(uuid4())

    @diagnostic_operations.diagnostic_job("npc_learning")
    async def operation(session_id, private_input):
        assert diagnostics.active.get() == {"session_id": identifier}
        return private_input

    assert await operation(identifier, PRIVATE) == PRIVATE
    assert [name for name, _ in diagnostics.events] == ["job.started", "job.completed"]
    assert all(fields["session_id"] == identifier for _, fields in diagnostics.events)
    assert diagnostics.events[0][1]["call_id"] == diagnostics.events[1][1]["call_id"]
    assert diagnostics.events[1][1]["duration_ms"] >= 0
    assert PRIVATE not in str(diagnostics.events)
    assert diagnostics.active.get() == {}


@pytest.mark.parametrize("error", [ValueError(PRIVATE), asyncio.CancelledError()])
async def test_job_failure_preserves_exception_and_releases_context(diagnostics, error):
    identifier = str(uuid4())

    @diagnostic_operations.diagnostic_job("memory_maintenance")
    async def operation(session_id):
        raise error

    with pytest.raises(type(error)) as raised:
        await operation(identifier)
    assert raised.value is error
    name, fields = diagnostics.events[-1]
    assert name == ("job.cancelled" if isinstance(error, asyncio.CancelledError) else "job.failed")
    assert fields["error"] is error
    assert set(fields) == {"session_id", "operation", "call_id", "duration_ms", "error"}
    assert diagnostics.active.get() == {}


async def test_disabled_job_does_not_create_events_or_context(diagnostics):
    diagnostics.enabled = False

    @diagnostic_operations.diagnostic_job("scene_background")
    async def operation(session_id):
        assert diagnostics.active.get() == {}
        return PRIVATE

    assert await operation(str(uuid4())) == PRIVATE
    assert diagnostics.events == []
