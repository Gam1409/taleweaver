"""Commit hook effects and their ledger marker together; retry only rolled-back I/O failures."""

from collections.abc import Awaitable, Callable
from typing import Any
from uuid import uuid4

from httpx import NetworkError, TimeoutException
from sqlalchemy import select

from backend.models.chat import ChatMessage
from backend.models.hook_run import HookRun


async def run(manager: Any, name: str, callback: Callable[[], Awaitable[Any]]) -> Any:
    db = manager.db
    boundary = getattr(manager, "_hook_boundary", None)
    if boundary is None:
        boundary = await db.scalar(
            select(ChatMessage.id)
            .where(ChatMessage.session_id == manager.game_id, ChatMessage.role == "user")
            .order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc())
            .limit(1)
        )
        boundary = boundary or str(uuid4())
        manager._hook_boundary = boundary
    key = (manager.game_id, boundary, name)
    row = await db.get(HookRun, key)
    if row and row.status in {"completed", "failed"}:
        return []
    # The caller's completed turn must already be durable before hook savepoints.
    await db.commit()
    for attempt in range((row.attempts if row else 0), 2):
        try:
            manager._atomic_post_turn_hook = True
            async with db.begin_nested():
                result = await callback()
                row = row or HookRun(session_id=key[0], boundary_id=key[1], hook_name=name)
                row.status, row.attempts, row.error_type = "completed", attempt + 1, None
                db.add(row)
                await db.flush()
            await db.commit()
            return result
        except Exception as error:
            await db.rollback()
            # A failed savepoint may expire ORM fields. Reload before any retry or final payload.
            await db.refresh(manager.state)
            await db.refresh(manager.avatar)
            retriable = isinstance(
                error, (TimeoutError, ConnectionError, TimeoutException, NetworkError)
            )
            row = await db.get(HookRun, key) or HookRun(
                session_id=key[0], boundary_id=key[1], hook_name=name
            )
            row.status = "retryable" if retriable and attempt == 0 else "failed"
            row.attempts, row.error_type = attempt + 1, type(error).__name__[:100]
            db.add(row)
            await db.commit()
            if row.status == "failed":
                raise
        finally:
            manager._atomic_post_turn_hook = False
    return []
