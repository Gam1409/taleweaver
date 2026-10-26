"""Identify retryable SQLite contention without treating other DB errors as locks."""

import sqlite3

from sqlalchemy.exc import DBAPIError


def is_sqlite_busy(error: BaseException) -> bool:
    original = error.orig if isinstance(error, DBAPIError) else error
    if not isinstance(original, sqlite3.OperationalError):
        return False
    code = getattr(original, "sqlite_errorcode", None)
    if isinstance(code, int):
        return code & 0xFF in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED)
    # Older drivers and hand-raised SQLite errors do not expose a numeric code.
    return (
        str(original)
        .lower()
        .startswith(("database is locked", "database table is locked", "database schema is locked"))
    )
