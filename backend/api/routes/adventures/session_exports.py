"""Portable session downloads for both UUID and legacy multilingual save IDs."""

import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.routes.adventures.session_transfer import export_archive_response
from backend.core.auth import get_current_user
from backend.core.database import get_db
from backend.engine.export_archives import SessionArchiveLimitError
from backend.models.game_session import GameSession
from backend.models.user import User

router = APIRouter(tags=["Sessions"])
logger = logging.getLogger(__name__)


@router.get("/sessions/{game_id}/export")
async def export_session_ads(
    game_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> StreamingResponse:
    """Export an owned save without putting Unicode into raw HTTP headers."""
    result = await db.execute(
        select(GameSession.id).where(
            GameSession.id == game_id, GameSession.user_id == current_user.id
        )
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Session not found.")

    try:
        return await export_archive_response(db, game_id)
    except SessionArchiveLimitError as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from None
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("ADS export failed")
        raise HTTPException(status_code=500, detail="Session export failed.") from exc
