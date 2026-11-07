"""Unicode case folding for bound SQLite search expressions, including Cyrillic."""

import unicodedata
from typing import Any

from sqlalchemy import event
from sqlalchemy.engine import Engine


def casefold(value: str | None) -> str:
    return unicodedata.normalize("NFKC", value or "").casefold()


def _install(connection: Any, _record: Any) -> None:
    create = getattr(connection, "create_function", None)
    if create is not None:
        create("tw_casefold", 1, casefold, deterministic=True)


def install() -> None:
    if not event.contains(Engine, "connect", _install):
        event.listen(Engine, "connect", _install)
