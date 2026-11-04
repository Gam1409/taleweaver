"""ComfyUI compatibility checks and prompt tools for settings drafts."""

import json
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.core.auth import get_current_admin
from backend.core.comfyui_config import ComfyPreset, ComfyWorkflow
from backend.core.comfyui_starter_models import LoaderRecipe
from backend.core.comfyui_starters import model_choices, starter_catalog
from backend.core.comfyui_task_templates import preset_catalog, task_preset
from backend.core.image_model_detection import detect_preset_template
from backend.core.image_prompt_templates import TEMPLATES
from backend.core.image_purposes import ImagePurpose
from backend.engine.comfyui_client import ComfyClient
from backend.engine.comfyui_validation import inspect_workflow, node_input_schema
from backend.engine.image_prompt_adapter import prepare_prompt
from backend.models.user import User

router = APIRouter(prefix="/comfyui", tags=["ComfyUI"])


class CheckWorkflow(BaseModel):
    url: str
    workflow: ComfyWorkflow


class DetectionRequest(BaseModel):
    graph: dict
    reference_graph: dict | None = None


class NodeSchemaRequest(BaseModel):
    url: str
    classes: list[str] = Field(min_length=1, max_length=256)


class PromptPreview(BaseModel):
    preset: ComfyPreset
    description: str = Field(min_length=1, max_length=12000)


@router.get("/prompt-templates", response_model=None)
async def prompt_templates(_user: User = Depends(get_current_admin)) -> list[dict[str, Any]]:
    return TEMPLATES


@router.get("/starter-workflows", response_model=None)
async def starter_workflows(_user: User = Depends(get_current_admin)) -> list[dict[str, Any]]:
    return starter_catalog()


class StarterPresetRequest(LoaderRecipe):
    family: str = Field(min_length=1, max_length=80)
    purpose: ImagePurpose


@router.get("/starter-presets", response_model=None)
async def starter_presets(_user: User = Depends(get_current_admin)) -> list[dict[str, Any]]:
    return preset_catalog()


@router.post("/starter-presets", response_model=None)
async def create_starter_preset(
    payload: StarterPresetRequest, _user: User = Depends(get_current_admin)
) -> dict[str, Any]:
    try:
        return task_preset(payload.family, payload.purpose, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/model-options", response_model=None)
async def workflow_model_options(
    payload: CheckWorkflow, _user: User = Depends(get_current_admin)
) -> list[dict[str, Any]]:
    try:
        async with ComfyClient(payload.url) as client:
            registry = await client.json("GET", "/object_info")
        if not isinstance(registry, dict):
            raise ValueError("Invalid node registry.")
        return model_choices(payload.workflow, registry)
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(
            400, "Could not load model filenames. Check the ComfyUI URL and connectivity."
        ) from exc


async def _node_registry(url: str) -> dict[str, Any]:
    try:
        async with ComfyClient(url) as client:
            registry = await client.json("GET", "/object_info")
        if not isinstance(registry, dict):
            raise ValueError("Invalid node registry.")
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(
            400, "Could not load node definitions. Check the ComfyUI URL and connectivity."
        ) from exc
    return registry


@router.post("/node-schemas", response_model=None)
async def node_input_schemas(
    payload: NodeSchemaRequest, _user: User = Depends(get_current_admin)
) -> dict[str, Any]:
    """Live widget/socket layouts for the workflow's node classes.

    The frontend importer uses this to name legacy positional ``widgets_values``
    of editor exports — including custom node packs this repo never heard of —
    instead of relying on a hardcoded table of core nodes.
    """
    registry = await _node_registry(payload.url)
    classes = list(dict.fromkeys(payload.classes))
    return {name: node_input_schema(registry.get(name)) for name in classes}


@router.post("/check-nodes", response_model=None)
async def check_node_types(
    payload: NodeSchemaRequest, _user: User = Depends(get_current_admin)
) -> dict[str, Any]:
    """Check installed node types without requiring a fully configured workflow."""
    registry = await _node_registry(payload.url)
    classes = sorted(set(payload.classes))
    missing = [name for name in classes if name not in registry]
    return {"node_types": len(classes), "missing_node_types": missing}


@router.post("/detect-template", response_model=None)
async def detect_prompt_template(
    payload: DetectionRequest, _user: User = Depends(get_current_admin)
) -> dict[str, Any]:
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


@router.post("/preview-prompt", response_model=None)
async def preview_prompt(
    payload: PromptPreview, user: User = Depends(get_current_admin)
) -> dict[str, Any]:
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


@router.post("/check", response_model=None)
async def check_workflow(
    payload: CheckWorkflow, _user: User = Depends(get_current_admin)
) -> dict[str, Any]:
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
