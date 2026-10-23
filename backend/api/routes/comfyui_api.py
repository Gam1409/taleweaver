"""Read-only ComfyUI compatibility checks for settings drafts."""

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.core.auth import get_current_admin
from backend.core.comfyui_config import ComfyWorkflow
from backend.engine.comfyui_client import ComfyClient
from backend.engine.comfyui_validation import inspect_workflow
from backend.models.user import User

router = APIRouter(prefix="/comfyui", tags=["ComfyUI"])


class CheckWorkflow(BaseModel):
    url: str
    workflow: ComfyWorkflow


@router.post("/check")
async def check_workflow(payload: CheckWorkflow, _user: User = Depends(get_current_admin)):
    try:
        async with ComfyClient(payload.url) as client:
            registry = await client.json("GET", "/object_info")
        if not isinstance(registry, dict):
            raise ValueError("The server did not return a ComfyUI node registry.")
        return inspect_workflow(payload.workflow, registry)
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(
            400, "Could not validate ComfyUI. Check the URL, connectivity and API workflow."
        ) from exc
