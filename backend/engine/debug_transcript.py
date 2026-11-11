"""One classification policy for durable Debug messages and legacy command transcripts."""

from collections.abc import Generator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, TypeVar

from sqlalchemy import and_, func, not_
from sqlalchemy.sql.elements import ColumnElement

from backend.models.chat import ChatMessage

T = TypeVar("T")


def field(row: Any, key: str, default: Any = None) -> Any:
    return row.get(key, default) if isinstance(row, Mapping) else getattr(row, key, default)


def is_debug_command(content: str) -> bool:
    # Match the command dispatcher's reserved prefix, not natural-language story words.
    return content.lstrip().lower().startswith("/debug")


def is_debug_message(row: Any) -> bool:
    if field(row, "is_debug", False):
        return True
    role, content = field(row, "role"), str(field(row, "content", "") or "")
    if role == "user":
        return is_debug_command(content)
    return role == "system" and content.lstrip().upper().startswith(
        ("[DEBUG", "DEBUG:", "--- DEBUG")
    )


@dataclass
class DebugTranscript:
    command: bool = False

    def is_debug(self, row: Any) -> bool:
        marked = is_debug_message(row)
        role = field(row, "role")
        if role == "user":
            self.command = marked
        elif role == "system":
            pending, self.command = self.command, False
            return marked or pending
        elif role == "assistant":
            self.command = False
        return marked


def without_debug(rows: list[T]) -> list[T]:
    classifier = DebugTranscript()
    return [row for row in rows if not classifier.is_debug(row)]


def not_debug_sql() -> ColumnElement[bool]:
    content = func.lower(func.ltrim(ChatMessage.content, " \t\r\n"))
    command = and_(ChatMessage.role == "user", content.startswith("/debug"))
    return and_(ChatMessage.is_debug.is_(False), not_(command))


@contextmanager
def debug_message_scope(manager: Any) -> Generator[None, None, None]:
    previous = getattr(manager, "_debug_message_scope", False)
    manager._debug_message_scope = True
    try:
        yield
    finally:
        manager._debug_message_scope = previous
