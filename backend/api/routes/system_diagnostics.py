"""Administrative control for metadata-only system diagnostics."""

import asyncio

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, StrictBool

from backend.core.auth import get_current_admin
from backend.core.system_diagnostics import service
from backend.models.user import User

router = APIRouter(prefix="/system-diagnostics", tags=["System diagnostics"])


class DiagnosticSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: StrictBool


@router.get("")
async def get_diagnostics(user: User = Depends(get_current_admin)) -> dict:
    return service.status()


@router.put("")
async def update_diagnostics(
    payload: DiagnosticSettings, user: User = Depends(get_current_admin)
) -> dict:
    try:
        return await asyncio.to_thread(service.set_enabled, payload.enabled)
    except OSError as error:
        raise HTTPException(
            503,
            "Could not save system diagnostics settings. Check local log directory permissions.",
        ) from error
