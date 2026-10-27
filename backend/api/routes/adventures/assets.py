import asyncio
import logging
import os
import re
import uuid
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.routes.adventures.schemas import SuggestPromptRequest, SuggestPromptResponse
from backend.core.auth import get_current_user
from backend.core.database import get_db
from backend.engine.media_engine import MediaEngine
from backend.models.adventure_template import AdventureTemplate
from backend.models.user import User
from backend.utils.path_security import (
    ensure_within_base_dir,
    ensure_within_data_dir,
    safe_data_path,
    sanitize_path_component,
)

__all__ = ["MediaEngine", "router"]

router = APIRouter(prefix="/{template_id}/visuals", tags=["Assets"])
logger = logging.getLogger(__name__)
_SAFE_IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}
_ALLOWED_VISUAL_TARGET_TYPES = {"cover", "scene", "npc", "object", "protagonist"}


def _build_visual_prompt(
    target_type: str,
    target_obj: Any,
    custom_prompt: Optional[str],
    *,
    style_instruction: Optional[str] = None,
    tone_instruction: Optional[str] = None,
) -> str:
    if custom_prompt and custom_prompt.strip():
        return custom_prompt.strip()

    prompt_suffix = ""
    if style_instruction:
        prompt_suffix += f" Style constraints: {style_instruction}."
    if tone_instruction:
        prompt_suffix += f" Narrative tone reference: {tone_instruction}."

    def get_attr(obj, attr, default=""):
        if isinstance(obj, dict):
            return obj.get(attr) or default
        return getattr(obj, attr, None) or default

    if target_type == "protagonist":
        name = get_attr(target_obj, "name", "The protagonist")
        role = get_attr(target_obj, "role", "adventurer")
        description = get_attr(target_obj, "description", "A distinctive fantasy hero.")
        return f"Portrait of character {name}, {role}. {description}. Game character art style.{prompt_suffix}"

    if target_type == "scene":
        label = get_attr(target_obj, "label") or get_attr(target_obj, "name") or "Scene"
        description = get_attr(target_obj, "description")
        return f"Atmospheric background: {label}. {description}. RPG visual novel style, high detail.{prompt_suffix}"

    if target_type == "npc":
        name = get_attr(target_obj, "name", "NPC")
        description = get_attr(target_obj, "description", "A distinctive non-player character.")
        return f"Portrait of NPC {name}. {description}. Character portrait, high detail.{prompt_suffix}"

    if target_type == "object":
        name = get_attr(target_obj, "name", "Object")
        description = get_attr(target_obj, "description", "A detailed fantasy object.")
        return f"Detailed illustration of object {name}. {description}. Fantasy item concept art, isolated and clearly readable.{prompt_suffix}"

    raise HTTPException(status_code=400, detail="Unsupported visual target type.")


def _sanitize_image_extension(filename: Optional[str]) -> str:
    if not filename or "." not in filename:
        return "png"
    ext = filename.rsplit(".", 1)[-1].strip().lower()
    return ext if ext in _SAFE_IMAGE_EXTENSIONS else "png"


def _extension_from_content_type(content_type: Optional[str]) -> str:
    ext_by_type = {
        "image/png": "png",
        "image/jpeg": "jpg",
        "image/webp": "webp",
    }
    return ext_by_type.get((content_type or "").strip().lower(), "png")


def _sanitize_filename_token(value: Optional[str]) -> Optional[str]:
    candidate = (value or "").strip()
    if not candidate:
        return None
    token = re.sub(r"[^A-Za-z0-9_-]+", "-", candidate).strip("-")
    return token[:96] or None


def _build_uploaded_visual_path(
    template_id: str,
    target_type: str,
    file_ext: str,
    trusted_target_token: Optional[str] = None,
) -> str:
    safe_template_id = sanitize_path_component(template_id)
    if not safe_template_id:
        raise ValueError("Invalid adventure template identifier.")

    safe_target_type = sanitize_path_component(target_type)
    if safe_target_type not in _ALLOWED_VISUAL_TARGET_TYPES:
        raise ValueError("Invalid visual target type.")

    safe_file_ext = _sanitize_image_extension(file_ext)
    base_storage_path = safe_data_path("adventures", "library", safe_template_id, "visuals")

    if safe_target_type == "cover":
        storage_path = base_storage_path
        filename = f"cover_{uuid.uuid4().hex}.{safe_file_ext}"
    else:
        storage_path = safe_data_path(
            "adventures", "library", safe_template_id, "visuals", safe_target_type
        )
        safe_token = _sanitize_filename_token(trusted_target_token)
        filename_prefix = safe_token or safe_target_type
        filename = f"{filename_prefix}_{uuid.uuid4().hex}.{safe_file_ext}"

    safe_storage_path = ensure_within_data_dir(storage_path)
    os.makedirs(safe_storage_path, exist_ok=True)
    candidate_path = ensure_within_data_dir(os.path.join(safe_storage_path, filename))
    return ensure_within_base_dir(candidate_path, safe_storage_path)


class RegenerateVisualRequest(BaseModel):
    target_type: Literal["cover", "scene", "npc", "object", "protagonist"]
    target_id: str
    prompt: Optional[str] = None
    use_advanced_model: Optional[bool] = None
    use_current_image: bool = False


@router.post("/regenerate")
async def regenerate_visual(
    template_id: str,
    payload: RegenerateVisualRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Regenerate a specific owned visual, preserving the old image on failure."""
    from backend.engine.image_profiles import image_timeout
    from backend.engine.story_visual_presets import story_t2i
    from backend.engine.visual_regeneration import regenerate_owned_visual

    adv = await db.get(AdventureTemplate, template_id)
    if not adv or adv.owner_id != current_user.id:
        raise HTTPException(status_code=404, detail="Adventure template not found")
    try:
        timeout = image_timeout(story_t2i(current_user.t2i_settings, adv))
        return await asyncio.wait_for(
            regenerate_owned_visual(db, adv, current_user, payload),
            timeout=timeout,
        )
    except HTTPException:
        raise
    except asyncio.TimeoutError as exc:
        raise HTTPException(
            504, "Visual generation timed out; a remote job may still be running."
        ) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        logger.exception("Visual regeneration failed")
        raise HTTPException(502, "Visual generation failed. The previous image was kept.") from exc


@router.post("/suggest-prompt", response_model=SuggestPromptResponse)
async def suggest_prompt(
    template_id: str,
    payload: SuggestPromptRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Generate an AI prompt suggestion based on the asset's description."""
    from backend.models.avatar import Avatar
    from backend.models.world_entity import WorldEntity, WorldScene

    adv = await db.get(AdventureTemplate, template_id)
    if not adv or adv.owner_id != current_user.id:
        raise HTTPException(status_code=404, detail="Adventure template not found")

    name = ""
    description = ""

    logger.info(
        "Suggesting prompt for %s (%s) in adventure %s",
        payload.target_type,
        payload.target_id,
        template_id,
    )

    if payload.target_type == "cover":
        name = adv.title
        description = adv.teaser or adv.original_prompt or ""
    elif payload.target_type == "protagonist":
        av_res = await db.execute(
            select(Avatar)
            .where(Avatar.template_id == template_id)
            .order_by(Avatar.created_at.asc(), Avatar.id.asc())
            .limit(1)
        )
        avatar = av_res.scalars().first()
        if avatar:
            name = avatar.name
            description = avatar.description
    elif payload.target_type == "scene":
        res = await db.execute(
            select(WorldScene).where(
                WorldScene.id == payload.target_id, WorldScene.template_id == template_id
            )
        )
        scene = res.scalars().first()
        if scene:
            name = scene.label
            description = scene.description
    elif payload.target_type in ["npc", "object"]:
        res = await db.execute(
            select(WorldEntity).where(
                WorldEntity.id == payload.target_id, WorldEntity.template_id == template_id
            )
        )
        entity = res.scalars().first()
        if entity:
            name = entity.name
            description = entity.description

    logger.info(
        "Resolved name '%s', description length: %d", name, len(description) if description else 0
    )

    if not description:
        logger.warning("No description found for %s %s", payload.target_type, payload.target_id)
        return SuggestPromptResponse(suggested_prompt="")

    from backend.engine.preset_prompt_suggestion import suggest_image_prompt

    suggested = await suggest_image_prompt(current_user, adv, payload, name, description)
    return SuggestPromptResponse(suggested_prompt=suggested)


@router.post("/upload")
async def upload_visual(
    template_id: str,
    target_type: Literal["cover", "scene", "npc", "object", "protagonist"] = Form(...),
    target_id: str = Form(...),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Manually upload a visual asset."""
    if sanitize_path_component(template_id) != template_id:
        raise HTTPException(status_code=400, detail="Invalid template ID format.")
    if not target_id or sanitize_path_component(target_id) != target_id:
        raise HTTPException(status_code=400, detail="Invalid target ID format.")

    from backend.api.routes.adventures.visual_upload import (
        resolve_visual_upload_target,
        validate_visual_upload_content,
        write_visual_upload,
    )

    adv = await db.get(AdventureTemplate, template_id)
    if not adv or adv.owner_id != current_user.id:
        raise HTTPException(status_code=404, detail="Adventure template not found")

    try:
        content = await file.read()
        validate_visual_upload_content(content, file.content_type, target_type)
        target = await resolve_visual_upload_target(db, adv, target_type, target_id)
        trusted_target_token = None if target_type == "cover" else target.id
        full_path = _build_uploaded_visual_path(
            adv.id,
            target_type,
            _extension_from_content_type(file.content_type),
            trusted_target_token=trusted_target_token,
        )
        relative_url = write_visual_upload(full_path, content)
        if target_type == "protagonist":
            target.profile_image = relative_url
        else:
            target.image_url = relative_url
        await db.commit()
        return {"status": "uploaded", "target_type": target_type, "image_url": relative_url}
    except HTTPException:
        raise
    except Exception:
        logger.exception("Failed to upload visual for %s", template_id)
        raise HTTPException(status_code=500, detail="Visual upload failed.") from None
