"""Keep diagnostic failure reasons useful without exposing database values."""

import re
import sqlite3

from sqlalchemy.exc import SQLAlchemyError

from backend.core.diagnostic_detail import operational_message
from backend.core.diagnostic_fields import safe_error

_DB_MODULES = {
    "sqlite3",
    "aiosqlite",
    "asyncpg",
    "psycopg",
    "psycopg2",
    "pg8000",
    "pymysql",
    "MySQLdb",
    "mysql",
    "pyodbc",
    "oracledb",
    "cx_Oracle",
    "mariadb",
}
_BEARER = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/-]+=*")
_URL_CREDENTIAL = re.compile(
    r"(?<![A-Za-z0-9+.-])([A-Za-z][A-Za-z0-9+.-]{0,31}://)[^\s/@:]+:[^\s/@]+@"
)


def _database_error(error: BaseException) -> bool:
    pending: list[BaseException] = [error]
    seen: set[int] = set()
    while pending:
        if len(seen) >= 32:
            return True
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        if isinstance(current, (SQLAlchemyError, sqlite3.Error)) or any(
            base.__module__.split(".", 1)[0] in _DB_MODULES for base in type(current).__mro__
        ):
            return True
        pending.extend(
            linked for linked in (current.__cause__, current.__context__) if linked is not None
        )
    return False


def _reason(error: BaseException, fallback: str) -> str:
    try:
        text = str(error)
    except Exception:
        return fallback
    text = _BEARER.sub("Bearer [credential excluded]", text)
    return operational_message(_URL_CREDENTIAL.sub(r"\1[credential excluded]@", text)) or fallback


def failure_reason(error: BaseException, fallback: str) -> str:
    """Database failures and their wrappers expose only a caller's neutral fallback."""
    return fallback if _database_error(error) else _reason(error, fallback)


def failure_details(error: BaseException) -> dict[str, object]:
    """Never include raw exception args or text from a database error chain."""
    details: dict[str, object] = {"error": safe_error(error)}
    if not _database_error(error):
        details["failure_reason"] = _reason(error, "")
    return details
