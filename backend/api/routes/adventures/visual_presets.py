"""Per-story selection of administrator-configured ComfyUI presets."""

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.auth import get_current_user
from backend.core.comfyui_presets import normalize_comfy_presets
from backend.core.database import get_db
from backend.core.image_purposes import PresetAssignment
from backend.engine.story_visual_presets import story_selection, story_t2i
from backend.models.adventure_template import AdventureTemplate
from backend.models.user import User

router = APIRouter(prefix="/{template_id}/visual-presets", tags=["Assets"])


class StoryPresets(BaseModel):
    source: Literal["saved", "current"] = "saved"
    selection: dict[PresetAssignment, str] = Field(default_factory=dict)


async def _owned(db: AsyncSession, template_id: str, user: User) -> AdventureTemplate:
    adventure = await db.get(AdventureTemplate, template_id)
    if not adventure or adventure.owner_id != user.id:
        raise HTTPException(404, "Adventure template not found.")
    return adventure


@router.get("", response_model=None)
async def read_presets(
    template_id: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
) -> dict[str, Any]:
    adventure = await _owned(db, template_id, user)
    t2i = normalize_comfy_presets(user.t2i_settings or {})
    return {
        "source": (adventure.original_manifest or {}).get("visual_preset_source", "saved"),
        "selection": story_selection(adventure),
        "presets": [
            {"id": key, "name": preset["name"]}
            for key, preset in t2i["comfyui_presets"].items()
            if preset.get("generate")
        ],
    }


@router.put("", response_model=None)
async def save_presets(
    template_id: str,
    payload: StoryPresets,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    adventure = await _owned(db, template_id, user)
    manifest = {
        **(adventure.original_manifest or {}),
        "visual_presets": payload.selection,
        "visual_preset_source": payload.source,
    }
    from types import SimpleNamespace

    try:
        story_t2i(
            normalize_comfy_presets(user.t2i_settings or {}),
            SimpleNamespace(original_manifest=manifest),
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    adventure.original_manifest = manifest
    await db.commit()
    return payload.model_dump()
