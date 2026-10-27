"""Validate, resolve and store manually uploaded adventure visuals."""

import os
from io import BytesIO

from fastapi import HTTPException
from PIL import Image
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import settings
from backend.core.visual_limits import VISUAL_LIMITS
from backend.models.adventure_template import AdventureTemplate
from backend.models.avatar import Avatar
from backend.models.world_entity import WorldEntity, WorldScene
from backend.utils.path_security import ensure_within_base_dir, ensure_within_data_dir

_ALLOWED_MIME_TYPES = {"image/png", "image/jpeg", "image/webp"}


def validate_visual_upload_content(content: bytes, content_type: str | None, target_type: str):
    """Reject unsupported images before selecting a target or writing any file."""
    if content_type and content_type not in _ALLOWED_MIME_TYPES:
        raise HTTPException(
            status_code=400, detail="Unsupported file type. Please use PNG, JPEG, or WEBP."
        )
    limits = VISUAL_LIMITS.get(target_type)
    if not limits:
        raise HTTPException(status_code=400, detail="Invalid visual target type.")
    if len(content) > int(limits["maxBytes"]):
        raise HTTPException(
            status_code=400,
            detail=f"Max file size for this asset is {int(limits['maxBytes']) // (1024 * 1024)} MB.",
        )
    try:
        with Image.open(BytesIO(content)) as image:
            width, height = image.size
    except Exception as error:
        raise HTTPException(status_code=400, detail="Could not read image dimensions.") from error
    if width > int(limits["maxWidth"]) or height > int(limits["maxHeight"]):
        raise HTTPException(
            status_code=400,
            detail=(
                f"Max size for this asset is {limits['maxWidth']}x{limits['maxHeight']} px. "
                f"Uploaded image is {width}x{height} px."
            ),
        )


async def resolve_visual_upload_target(
    db: AsyncSession, adventure: AdventureTemplate, target_type: str, target_id: str
) -> AdventureTemplate | Avatar | WorldScene | WorldEntity:
    """Resolve only template assets after the route has verified ownership."""
    if target_type == "cover":
        return adventure
    if target_type == "protagonist":
        statement = (
            select(Avatar)
            .where(Avatar.template_id == adventure.id)
            .order_by(Avatar.created_at.asc(), Avatar.id.asc())
            .limit(1)
        )
        missing_detail = "Protagonist not found for this adventure"
    elif target_type == "scene":
        statement = select(WorldScene).where(
            WorldScene.template_id == adventure.id,
            WorldScene.session_id.is_(None),
            WorldScene.id == target_id,
        )
        missing_detail = "Scene not found for this adventure"
    elif target_type in {"npc", "object"}:
        statement = select(WorldEntity).where(
            WorldEntity.template_id == adventure.id,
            WorldEntity.session_id.is_(None),
            WorldEntity.id == target_id,
        )
        missing_detail = "Entity not found for this adventure"
    else:
        raise HTTPException(status_code=400, detail="Invalid visual target type.")
    result = await db.execute(statement)
    target = result.scalars().first()
    if not target:
        raise HTTPException(status_code=404, detail=missing_detail)
    return target


def write_visual_upload(full_path: str, content: bytes) -> str:
    """Recheck path containment at the write sink and return its public data URL."""
    safe_parent_dir = ensure_within_data_dir(os.path.dirname(full_path))
    full_path = ensure_within_base_dir(full_path, safe_parent_dir)
    data_root = os.path.realpath(settings.DATA_DIR)
    if os.path.commonpath([os.path.realpath(full_path), data_root]) != data_root:
        raise HTTPException(status_code=400, detail="Invalid upload path.")
    with open(full_path, "wb") as file:
        file.write(content)
    rel_path = os.path.relpath(full_path, settings.DATA_DIR).replace("\\", "/")
    return f"/data/{rel_path}"
