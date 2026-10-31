"""Administrative recovery; a health check alone cannot prove generation stopped."""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from backend.core.auth import get_current_admin
from backend.core.inference import admission
from backend.core.inference.registry import InferenceQueueError
from backend.models.user import User

router = APIRouter(prefix="/inference-queue", tags=["Inference queue"])


class AcknowledgeStopped(BaseModel):
    model_config = ConfigDict(extra="forbid")
    endpoint_id: str = Field(pattern=r"^[a-f0-9]{64}(?::concurrent)?$")
    token: str = Field(min_length=1, max_length=36)
    confirmation: Literal["REMOTE_GENERATION_STOPPED"]


@router.get("")
async def status(user: User = Depends(get_current_admin)) -> dict:
    try:
        return {"enabled": admission.enabled(), "reservations": admission.registry().status()}
    except (OSError, ValueError) as error:
        raise HTTPException(
            503, "Inference journal cannot be read. Check local storage."
        ) from error


@router.post("/acknowledge-stopped")
async def acknowledge(payload: AcknowledgeStopped, user: User = Depends(get_current_admin)) -> dict:
    try:
        admission.registry().acknowledge_stopped(payload.endpoint_id, payload.token)
    except InferenceQueueError as error:
        raise HTTPException(409, str(error)) from error
    except (OSError, ValueError) as error:
        raise HTTPException(
            503, "Inference journal cannot be updated. Check local storage."
        ) from error
    return {"ok": True}
