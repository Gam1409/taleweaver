"""Content-language resolution shared by turn services and routes."""

from typing import Any

from backend.core.content_language import default_language, normalize_language


def resolve_content_language(
    state: Any, user: Any, adventure: Any, requested: str | None = None
) -> str:
    """A legacy per-request override takes priority over the saved session choice."""
    if requested:
        return normalize_language(requested) or "English"
    session = state.session if state is not None else None
    return default_language(
        getattr(session, "content_language", None),
        getattr(user, "default_language", None),
        getattr(adventure, "language", None),
    )


def initialize_content_language(state: Any, user: Any, adventure: Any) -> str:
    """Freeze the initial default on first access, including for older sessions."""
    language = resolve_content_language(state, user, adventure)
    if state.session is not None and state.session.content_language != language:
        state.session.content_language = language
    return language
