"""Request-local LLM exchanges for an owner's image details, never ordinary logs."""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

_MAX_CALLS = 4
_MAX_TEXT = 32000
_queries: ContextVar[list[dict] | None] = ContextVar("visual_queries", default=None)


@contextmanager
def collect_queries() -> Iterator[list[dict]]:
    queries: list[dict] = []
    token = _queries.set(queries)
    try:
        yield queries
    finally:
        _queries.reset(token)


def capture_query(
    system: str, user: str, response: str, model: str, operation: str | None = None
) -> None:
    queries = _queries.get()
    if queries is None or len(queries) >= _MAX_CALLS:
        return
    texts = {"system_prompt": system, "user_prompt": user, "response": response}
    queries.append(
        {
            **{key: value[:_MAX_TEXT] for key, value in texts.items()},
            "model": model[:256],
            "operation": "Scene analysis" if operation == "visible_frame" else "Visual prompt",
            "truncated": any(len(value) > _MAX_TEXT for value in texts.values()),
        }
    )
