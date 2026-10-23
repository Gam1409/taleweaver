"""Portable session downloads for both UUID and legacy multilingual save IDs."""

import io
import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.auth import get_current_user
from backend.core.database import get_db
from backend.engine.session_exporter import SessionExporter
from backend.models.game_session import GameSession
from backend.models.user import User
from backend.utils.download_headers import attachment_disposition

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
        zip_data = await SessionExporter.export_ads(db, game_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("ADS export failed")
        raise HTTPException(status_code=500, detail="Session export failed.") from exc

    # RFC 6266 / 5987: legacy IDs may contain Cyrillic or other Unicode letters.
    return StreamingResponse(
        io.BytesIO(zip_data),
        media_type="application/zip",
        headers={"Content-Disposition": attachment_disposition(f"session_{game_id}.ads")},
    )
