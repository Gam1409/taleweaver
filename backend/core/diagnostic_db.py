"""Database timings without SQL text, bound values, results or connection details."""

import time

from sqlalchemy import event

_OPERATIONS = {"SELECT", "INSERT", "UPDATE", "DELETE", "BEGIN", "COMMIT", "ROLLBACK", "PRAGMA"}
_TRANSACTION_KEY = "system_diagnostic_transaction"


def _service():
    from backend.core.system_diagnostics import service

    return service


def _before_cursor(_connection, _cursor, statement, _parameters, context, _many):
    if not _service().enabled:
        return
    keyword = statement.lstrip().split(None, 1)[0].upper() if statement.strip() else "OTHER"
    operation = keyword if keyword in _OPERATIONS else "OTHER"
    context.system_diagnostic_query = (time.perf_counter(), operation)


def _query_fields(context) -> dict:
    timing = getattr(context, "system_diagnostic_query", None)
    if timing is None:
        return {"operation": "OTHER"}
    started, operation = timing
    return {"operation": operation, "duration_ms": (time.perf_counter() - started) * 1000}


def _after_cursor(_connection, _cursor, _statement, _parameters, context, _many):
    if getattr(context, "system_diagnostic_query", None) is not None:
        _service().emit("db.query", **_query_fields(context))


def _handle_error(context):
    _service().emit(
        "db.error", error=context.original_exception, **_query_fields(context.execution_context)
    )


def _begin(connection):
    if not _service().enabled:
        return
    connection.info[_TRANSACTION_KEY] = time.perf_counter()
    _service().emit("db.transaction", operation="BEGIN")


def _end(connection, operation):
    started = connection.info.pop(_TRANSACTION_KEY, None)
    if started is not None:
        _service().emit(
            "db.transaction",
            operation=operation,
            duration_ms=(time.perf_counter() - started) * 1000,
        )


def _commit(connection):
    _end(connection, "COMMIT")


def _rollback(connection):
    _end(connection, "ROLLBACK")


def install_diagnostics(engine) -> None:
    """Install once; disabled diagnostics do not change SQL or transaction behavior."""
    target = getattr(engine, "sync_engine", engine)
    if event.contains(target, "before_cursor_execute", _before_cursor):
        return
    for name, callback in (
        ("before_cursor_execute", _before_cursor),
        ("after_cursor_execute", _after_cursor),
        ("handle_error", _handle_error),
        ("begin", _begin),
        ("commit", _commit),
        ("rollback", _rollback),
    ):
        event.listen(target, name, callback)
