"""Debug display toggles are not story inputs and do not replace replay boundaries."""

from sqlalchemy import and_, func, not_
from sqlalchemy.sql.elements import ColumnElement

from backend.models.chat import ChatMessage

DEBUG_TOGGLES = ("on", "off", "log on", "log off")


def is_debug_toggle(text: str) -> bool:
    return text.startswith("/debug ") and text[7:].strip().lower() in DEBUG_TOGGLES


def story_message_filter() -> ColumnElement[bool]:
    arguments = func.lower(func.trim(func.substr(ChatMessage.content, 8), " \t\r\n"))
    toggle = and_(
        ChatMessage.role == "user",
        ChatMessage.content.startswith("/debug "),
        arguments.in_(DEBUG_TOGGLES),
    )
    return and_(ChatMessage.role.in_(["user", "assistant"]), not_(toggle))
