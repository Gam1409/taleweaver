"""Existing SQL observers join rejection traces without asserting commit success."""

import asyncio
import sqlite3
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError, OperationalError, StatementError
from sqlalchemy.pool import NullPool

from backend.core import diagnostic_db
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


@pytest.fixture
def observed_database(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'diagnostic-fixture.db'}")
    diagnostic_db.install_diagnostics(engine)
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE records (id INTEGER PRIMARY KEY, note TEXT)"))
    try:
        yield engine
    finally:
        engine.dispose()


def test_trace_only_packet_includes_query_transaction_error_and_statement_hooks(observed_database):
    from backend.core.state_rejection_trace import reject, scope

    service.set_enabled(True, state_failure_traces=True)
    private = "synthetic-bound-value-must-not-be-recorded"
    with scope(operation="persistence_validation"):
        with observed_database.begin() as connection:
            connection.execute(
                text("INSERT INTO records (id, note) VALUES (:id, :note)"),
                {"id": 1, "note": private},
            )
        with pytest.raises(IntegrityError), observed_database.begin() as connection:
            connection.execute(
                text("INSERT INTO records (id, note) VALUES (:id, :note)"),
                {"id": 1, "note": private},
            )
        reject("state", "persistence_rejected", "The duplicate fixture record was rejected.")
    rows = trace_rows()
    assert event_payloads(rows, "detail.db.query")
    queries = event_payloads(rows, "db.query")
    assert len(queries) == 1 and queries[0]["operation"] == "INSERT"
    assert queries[0]["duration_ms"] >= 0
    transactions = event_payloads(rows, "db.transaction")
    assert {payload["operation"] for payload in transactions} == {"BEGIN", "COMMIT", "ROLLBACK"}
    assert all(payload["transaction_observation"] == "attempted" for payload in transactions)
    assert event_payloads(rows, "db.error")[0]["error"]["type"] == "IntegrityError"
    assert private not in trace_files()[0].read_text()
    assert "INSERT INTO records" not in (service.directory / "system-debug.jsonl").read_text()


def test_commit_failure_is_an_attempt_and_preserves_the_original_db_error(
    observed_database, monkeypatch
):
    from backend.core.state_rejection_trace import scope

    service.set_enabled(True, state_failure_traces=True)
    original = observed_database.dialect.do_commit

    def unavailable(_connection):
        raise sqlite3.OperationalError("Synthetic commit failure")

    monkeypatch.setattr(observed_database.dialect, "do_commit", unavailable)
    with (
        pytest.raises(OperationalError, match="Synthetic commit failure"),
        scope(operation="failed_persistence"),
        observed_database.connect() as connection,
    ):
        transaction = connection.begin()
        connection.execute(
            text("INSERT INTO records (id, note) VALUES (:id, :note)"),
            {"id": 1, "note": "neutral fixture"},
        )
        transaction.commit()
    monkeypatch.setattr(observed_database.dialect, "do_commit", original)
    rows = trace_rows()
    transactions = event_payloads(rows, "db.transaction")
    commit = next(payload for payload in transactions if payload["operation"] == "COMMIT")
    assert commit["transaction_observation"] == "attempted"
    assert event_payloads(rows, "db.error")[0]["error"]["type"] == "OperationalError"
    assert event_payloads(rows, "state.rejected")[0]["reason_code"] == "operation_failed"
    # A failed commit can leave an uncommitted DBAPI transaction in the pooled
    # connection. Verify persistence using a genuinely distinct connection.
    independent = create_engine(observed_database.url, poolclass=NullPool)
    try:
        with independent.connect() as connection:
            assert connection.scalar(text("SELECT COUNT(*) FROM records")) == 0
    finally:
        independent.dispose()


def test_metadata_capture_failure_cannot_change_a_database_result(observed_database, monkeypatch):
    from backend.core import state_rejection_trace as traces

    service.set_enabled(True, state_failure_traces=True)

    def unavailable(*_args):
        raise ValueError("Synthetic metadata capture failure")

    monkeypatch.setattr(traces, "record", unavailable)
    with observed_database.begin() as connection:
        assert (
            connection.scalar(text("SELECT :value"), {"value": "unchanged fixture result"})
            == "unchanged fixture result"
        )
    assert service.write_failed is True


def test_foreground_debug_can_explicitly_reuse_parent_until_persistence_completes():
    from backend.core.state_rejection_trace import reject, scope

    service.set_enabled(True, state_failure_traces=True)
    session_id, turn_id = str(uuid4()), str(uuid4())
    with scope(session_id=session_id, turn_id=turn_id, operation="turn"):
        with scope(session_id=session_id, operation="debug_state", reuse_parent=True):
            reject("state", "debug_rejected", "The debug operation was rejected.")
        assert trace_files() == []
        service.emit("db.transaction", operation="COMMIT")
    assert len(trace_files()) == 1
    rows = trace_rows()
    assert rows[0]["context"]["operation"] == "turn"
    assert rows[0]["context"]["turn_id"] == turn_id
    assert event_payloads(rows, "db.transaction")


async def test_reuse_parent_never_merges_an_explicit_background_task():
    from backend.core.state_rejection_trace import reject, scope

    service.set_enabled(True, state_failure_traces=True)
    session_id, turn_id = str(uuid4()), str(uuid4())

    async def background():
        with scope(session_id=session_id, operation="debug_state", reuse_parent=True):
            reject("state", "background_rejected", "The background operation was rejected.")

    with scope(session_id=session_id, turn_id=turn_id, operation="turn"):
        await asyncio.create_task(background())
    assert len(trace_files()) == 1
    assert trace_rows()[0]["context"]["operation"] == "debug_state"
    assert trace_rows()[0]["context"]["turn_id"] is None


@pytest.mark.parametrize("boundary", ["scope", "async_step", "sync_step"])
@pytest.mark.parametrize("detailed_logging", [False, True])
async def test_core_value_error_chained_from_sql_never_records_bound_parameters(
    boundary, detailed_logging
):
    from types import SimpleNamespace

    from backend.core.engine_detailed_trace import step, sync_step
    from backend.core.state_rejection_trace import scope

    service.set_enabled(True, detailed_logging=detailed_logging, state_failure_traces=True)
    private = "synthetic-bound-parameter-must-remain-private"
    owner = SimpleNamespace(state=SimpleNamespace(inventory=[]))

    def fail():
        error = StatementError(
            "Synthetic database failure",
            "INSERT INTO records VALUES (:value)",
            {"value": private},
            sqlite3.DatabaseError("Synthetic error"),
        )
        try:
            raise error
        except StatementError as original:
            raise ValueError(str(original)) from original

    @step("synthetic.async.failure")
    async def fail_async(_owner):
        fail()

    @sync_step("synthetic.sync.failure")
    def fail_sync(_owner):
        fail()

    with pytest.raises(ValueError) as raised, scope(operation="wrapped_database_failure"):
        if boundary == "async_step":
            await fail_async(owner)
        elif boundary == "sync_step":
            fail_sync(owner)
        else:
            fail()
    assert private in str(raised.value)
    assert private not in trace_files()[0].read_text()
    assert private not in (service.directory / "system-debug.jsonl").read_text()
    assert (
        event_payloads(trace_rows(), "state.rejected")[0]["details"]["error"]["type"]
        == "ValueError"
    )
