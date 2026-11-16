"""Keep task cancellation authoritative when database cleanup raises a second error."""

import asyncio


def find_cancellation(error: BaseException) -> asyncio.CancelledError | None:
    pending = [error]
    visited: set[int] = set()
    while pending:
        current = pending.pop()
        if id(current) in visited:
            continue
        visited.add(id(current))
        if isinstance(current, asyncio.CancelledError):
            return current
        pending.extend(
            linked for linked in (current.__cause__, current.__context__) if linked is not None
        )
    return None
