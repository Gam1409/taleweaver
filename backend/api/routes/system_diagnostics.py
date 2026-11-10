"""Administrative control for standard and explicitly enabled detailed diagnostics."""

import asyncio

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, StrictBool
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.auth import get_current_admin
from backend.core.database import get_db
from backend.core.reliability_metrics import snapshot
from backend.core.system_diagnostics import service
from backend.models.hook_run import HookRun
from backend.models.user import User

router = APIRouter(prefix="/system-diagnostics", tags=["System diagnostics"])


class DiagnosticSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: StrictBool
    detailed_logging: StrictBool = False


@router.get("")
async def get_diagnostics(
    user: User = Depends(get_current_admin), db: AsyncSession = Depends(get_db)
) -> dict:
    rows = (await db.scalars(select(HookRun).order_by(HookRun.updated_at.desc()).limit(20))).all()
    return {
        **service.status(),
        "reliability": {
            **snapshot(),
            "hooks": [
                {
                    "name": row.hook_name,
                    "status": row.status,
                    "attempts": row.attempts,
                    "error_type": row.error_type,
                    "updated_at": row.updated_at.isoformat(),
                }
                for row in rows
            ],
        },
    }


@router.put("")
async def update_diagnostics(
    payload: DiagnosticSettings, user: User = Depends(get_current_admin)
) -> dict:
    try:
        return {
            **await asyncio.to_thread(
                service.set_enabled, payload.enabled, detailed_logging=payload.detailed_logging
            ),
            "reliability": snapshot(),
        }
    except OSError as error:
        raise HTTPException(
            503,
            "Could not save system diagnostics settings. Check local log directory permissions.",
        ) from error
