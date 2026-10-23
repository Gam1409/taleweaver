"""ComfyUI compatibility checks and prompt tools for settings drafts."""

import json

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.core.auth import get_current_admin
from backend.core.comfyui_config import ComfyPreset, ComfyWorkflow
from backend.core.image_model_detection import detect_preset_template
from backend.core.image_prompt_templates import TEMPLATES
from backend.engine.comfyui_client import ComfyClient
from backend.engine.comfyui_validation import inspect_workflow
from backend.engine.image_prompt_adapter import prepare_prompt
from backend.models.user import User

router = APIRouter(prefix="/comfyui", tags=["ComfyUI"])


class CheckWorkflow(BaseModel):
    url: str
    workflow: ComfyWorkflow


class DetectionRequest(BaseModel):
    graph: dict
    reference_graph: dict | None = None


class PromptPreview(BaseModel):
    preset: ComfyPreset
    description: str = Field(min_length=1, max_length=12000)


@router.get("/prompt-templates")
async def prompt_templates(_user: User = Depends(get_current_admin)):
    return TEMPLATES


@router.post("/detect-template")
async def detect_prompt_template(
    payload: DetectionRequest, _user: User = Depends(get_current_admin)
):
    for graph in (payload.graph, payload.reference_graph):
        if graph is not None and (
            len(graph) > 256
            or len(json.dumps(graph).encode()) > 262144
            or any(
                not isinstance(n, dict)
                or not isinstance(n.get("class_type"), str)
                or not isinstance(n.get("inputs"), dict)
                for n in graph.values()
            )
        ):
            raise HTTPException(422, "Invalid API workflow.")
    return detect_preset_template(payload.graph, payload.reference_graph)


@router.post("/preview-prompt")
async def preview_prompt(payload: PromptPreview, user: User = Depends(get_current_admin)):
    options = {
        "comfyui_presets": {"preview": payload.preset.model_dump()},
        "comfyui_assignments": {"simple": "preview"},
        "_prompt_user": user,
    }
    try:
        return await prepare_prompt(payload.description, options)
    except Exception as exc:
        raise HTTPException(
            400, "Prompt preview failed. Check workflow, template and Small/Utility LLM settings."
        ) from exc


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
