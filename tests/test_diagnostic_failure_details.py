"""Diagnostic failure details exclude DB values and retain safe neutral reasons."""

import sqlite3

import pytest
from sqlalchemy.exc import DBAPIError, StatementError

from backend.core.diagnostic_failures import failure_details, failure_reason

SENTINEL = "SYNTHETIC-PRIVATE-BOUND-VALUE"


@pytest.mark.parametrize("wrapped", [False, True])
@pytest.mark.parametrize("error_type", ["statement", "dbapi", "sqlite", "driver"])
def test_direct_and_chained_database_errors_have_only_safe_metadata(error_type, wrapped):
    original = sqlite3.DatabaseError(SENTINEL)
    if error_type == "statement":
        error = StatementError(SENTINEL, "UPDATE neutral SET value=?", (SENTINEL,), original)
    elif error_type == "dbapi":
        error = DBAPIError("UPDATE neutral SET value=?", (SENTINEL,), original)
    elif error_type == "driver":
        error = type("DatabaseError", (Exception,), {"__module__": "psycopg.errors"})(SENTINEL)
    else:
        error = original
    if wrapped:
        outer = ValueError(f"Update failed: {error}")
        outer.__context__ = error
        error = outer
    assert failure_reason(error, "Database update failed.") == "Database update failed."
    details = failure_details(error)
    assert set(details) == {"error"}
    assert SENTINEL not in str(details)


@pytest.mark.parametrize(
    "error", [ValueError("Neutral validation reason"), ConnectionError("Neutral provider reason")]
)
def test_neutral_provider_and_validation_reasons_remain_available(error):
    assert failure_reason(error, "Fallback") == str(error)
    assert failure_details(error)["failure_reason"] == str(error)
    assert "failure_args" not in failure_details(error)


def test_reason_redaction_handles_long_unbroken_text_and_credentials():
    prefix = "a" * 120_000
    error = ValueError(
        prefix
        + " https://synthetic-user:synthetic-password@example.test/ Bearer synthetic-credential"
    )
    reason = failure_reason(error, "Fallback")
    assert reason.startswith(prefix)
    assert "synthetic-user" not in reason
    assert "synthetic-password" not in reason
    assert "synthetic-credential" not in reason
    assert reason == failure_details(error)["failure_reason"]


def test_cyclic_database_cause_walk_terminates_without_exposing_values():
    outer = ValueError(SENTINEL)
    original = sqlite3.DatabaseError(SENTINEL)
    outer.__cause__ = original
    original.__context__ = outer
    assert failure_reason(outer, "Fallback") == "Fallback"
    assert set(failure_details(outer)) == {"error"}
