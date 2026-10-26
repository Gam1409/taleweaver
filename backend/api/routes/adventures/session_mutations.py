"""Keep direct session mutations from interleaving with a streamed game turn."""

from collections.abc import AsyncIterator
from contextlib import ExitStack, asynccontextmanager

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.auth import get_current_user
from backend.core.database import get_db
from backend.engine.visual_novel.concurrency import (
    BUSY_DETAIL,
    SessionBusyError,
    session_write_lease,
)
from backend.models.game_session import GameSession
from backend.models.user import User


async def session_mutation_lease(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> AsyncIterator[None]:
    """Authorize before rejecting busy sessions; acquire before loading mutable state.

    This nonblocking lease matches the standard single-worker launcher. It lasts
    through the endpoint's commit and is released on errors or cancellation.
    """
    game_id = request.path_params.get("game_id")
    endpoint = request.scope.get("endpoint")
    if game_id and getattr(endpoint, "__name__", "") == "get_chat_history":
        async with _snapshot_scope(db, game_id):
            yield
        return
    if (
        not game_id
        or request.method in {"GET", "HEAD", "OPTIONS"}
        or getattr(endpoint, "__name__", "") in {"post_chat_message", "translate_text"}
    ):
        yield
        return
    owned_id = await db.scalar(
        select(GameSession.id).where(GameSession.id == game_id, GameSession.user_id == user.id)
    )
    if owned_id is None:
        raise HTTPException(404, "Session not found.")
    try:
        with session_write_lease(game_id):
            yield
    except SessionBusyError:
        raise HTTPException(409, BUSY_DETAIL) from None


@asynccontextmanager
async def _snapshot_scope(db: AsyncSession, game_id: str) -> AsyncIterator[None]:
    """Allow polling during a turn, but never repair or advance state in that poll."""
    with ExitStack() as leases:
        try:
            leases.enter_context(session_write_lease(game_id))
        except SessionBusyError:
            db.info["snapshot_read_only"] = True
        previous_autoflush = db.autoflush
        read_only = bool(db.info.get("snapshot_read_only"))
        if read_only:
            db.autoflush = False
        try:
            yield
        finally:
            db.info.pop("snapshot_read_only", None)
            db.autoflush = previous_autoflush
            if read_only:
                await db.rollback()
