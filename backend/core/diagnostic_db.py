"""Database timings and opt-in statement text; never capture bound credentials."""

import time

from sqlalchemy import event
from sqlalchemy.engine import Connection, Engine, ExceptionContext, ExecutionContext
from sqlalchemy.ext.asyncio import AsyncEngine

from backend.core.system_diagnostics import DiagnosticService

_OPERATIONS = {"SELECT", "INSERT", "UPDATE", "DELETE", "BEGIN", "COMMIT", "ROLLBACK", "PRAGMA"}
_TRANSACTION_KEY = "system_diagnostic_transaction"


def _service() -> DiagnosticService:
    from backend.core.system_diagnostics import service

    return service


def _before_cursor(
    _connection: Connection,
    _cursor: object,
    statement: str,
    _parameters: object,
    context: ExecutionContext,
    _many: bool,
) -> None:
    if not _service().enabled:
        return
    keyword = statement.lstrip().split(None, 1)[0].upper() if statement.strip() else "OTHER"
    operation = keyword if keyword in _OPERATIONS else "OTHER"
    context.__dict__["system_diagnostic_query"] = (time.perf_counter(), operation)
    if getattr(_service(), "capture_token", lambda: None)() is not None:
        _service().detail(
            "detail.db.query", statement=statement, operation=operation, executemany=_many
        )


def _query_fields(context: ExecutionContext | None) -> dict:
    timing = getattr(context, "system_diagnostic_query", None)
    if timing is None:
        return {"operation": "OTHER"}
    started, operation = timing
    return {"operation": operation, "duration_ms": (time.perf_counter() - started) * 1000}


def _after_cursor(
    _connection: Connection,
    _cursor: object,
    _statement: str,
    _parameters: object,
    context: ExecutionContext,
    _many: bool,
) -> None:
    if getattr(context, "system_diagnostic_query", None) is not None:
        _service().emit("db.query", **_query_fields(context))


def _handle_error(context: ExceptionContext) -> None:
    _service().emit(
        "db.error", error=context.original_exception, **_query_fields(context.execution_context)
    )


def _begin(connection: Connection) -> None:
    if not _service().enabled:
        return
    connection.info[_TRANSACTION_KEY] = time.perf_counter()
    _service().emit("db.transaction", operation="BEGIN")


def _end(connection: Connection, operation: str) -> None:
    started = connection.info.pop(_TRANSACTION_KEY, None)
    if started is not None:
        _service().emit(
            "db.transaction",
            operation=operation,
            duration_ms=(time.perf_counter() - started) * 1000,
        )


def _commit(connection: Connection) -> None:
    _end(connection, "COMMIT")


def _rollback(connection: Connection) -> None:
    _end(connection, "ROLLBACK")


def install_diagnostics(engine: Engine | AsyncEngine) -> None:
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
