"""Owner-only preview and download of an upstream-compatible publication copy."""

import asyncio

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.auth import get_current_user
from backend.core.database import get_db
from backend.engine.adventure_exporter import AdventureExporter
from backend.models.adventure_template import AdventureTemplate
from backend.models.user import User
from backend.services.adventure_publication import PublicationError, prepare_bundle
from backend.utils.download_headers import attachment_disposition

router = APIRouter(tags=["Adventures"])


class PublicationRequest(BaseModel):
    acknowledge_changes: bool = False


async def _prepare(db: AsyncSession, user: User, template_id: str) -> tuple[bytes, dict]:
    owned = await db.scalar(
        select(AdventureTemplate.id).where(
            AdventureTemplate.id == template_id, AdventureTemplate.owner_id == user.id
        )
    )
    if owned is None:
        raise HTTPException(404, "Adventure not found.")
    try:
        data = await AdventureExporter.export_adz(db, template_id)
        return await asyncio.to_thread(prepare_bundle, data)
    except PublicationError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/templates/{template_id}/publication/preview")
async def preview_publication(
    template_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    _, report = await _prepare(db, user, template_id)
    return report


@router.post("/templates/{template_id}/publication/export")
async def export_publication(
    template_id: str,
    payload: PublicationRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    data, report = await _prepare(db, user, template_id)
    if report["requires_acknowledgement"] and not payload.acknowledge_changes:
        raise HTTPException(
            409, {"message": "Review and acknowledge compatibility changes.", "report": report}
        )
    return Response(
        data,
        media_type="application/zip",
        headers={"Content-Disposition": attachment_disposition(f"publication_{template_id}.adz")},
    )
