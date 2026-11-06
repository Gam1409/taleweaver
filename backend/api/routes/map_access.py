"""Authorize the complete map scope before taking a session mutation lease."""

from collections.abc import AsyncIterator

from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.auth import get_current_user
from backend.core.database import get_db
from backend.engine.visual_novel.concurrency import (
    BUSY_DETAIL,
    SessionBusyError,
    session_write_lease,
)
from backend.models.adventure_template import AdventureTemplate
from backend.models.game_session import GameSession
from backend.models.user import User


async def authorize_map(
    request: Request,
    template_id: str,
    session_id: str | None = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> AsyncIterator[None]:
    is_admin = user.role == "admin"
    if session_id is None:
        template = await db.get(AdventureTemplate, template_id)
        if template is None or (template.owner_id != user.id and not is_admin):
            raise HTTPException(404, "Adventure template not found.")
        yield
        return
    session = await db.get(GameSession, session_id)
    if (
        session is None
        or session.template_id != template_id
        or (session.user_id != user.id and not is_admin)
    ):
        raise HTTPException(404, "Session not found.")
    if request.method in {"GET", "HEAD", "OPTIONS"}:
        yield
        return
    try:
        with session_write_lease(session_id):
            yield
    except SessionBusyError:
        raise HTTPException(409, BUSY_DETAIL) from None
