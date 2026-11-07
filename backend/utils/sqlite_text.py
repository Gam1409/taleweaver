"""Unicode case folding for bound SQLite search expressions, including Cyrillic."""

import json
import unicodedata
from functools import lru_cache
from typing import Any

from sqlalchemy import event
from sqlalchemy.engine import Engine


def casefold(value: str | None) -> str:
    return unicodedata.normalize("NFKC", value or "").casefold()


@lru_cache(maxsize=128)
def _terms(serialized: str) -> tuple[str, ...]:
    return tuple(json.loads(serialized))


def contains_any(value: str | None, serialized: str) -> int:
    # Normalize a potentially long transcript row once, rather than once per term.
    text = casefold(value)
    return int(any(term in text for term in _terms(serialized)))


def _install(connection: Any, _record: Any) -> None:
    create = getattr(connection, "create_function", None)
    if create is not None:
        create("tw_casefold", 1, casefold, deterministic=True)
        create("tw_contains_any", 2, contains_any, deterministic=True)


def install() -> None:
    if not event.contains(Engine, "connect", _install):
        event.listen(Engine, "connect", _install)
