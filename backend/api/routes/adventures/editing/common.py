"""Shared editor helpers: ID sanitizing, ownership checks, avatar lookup, lock fields."""

import logging
import os
import re
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.engine.gameplay.world import AdventureLogic
from backend.engine.template_avatar import avatar_from_manifest, get_template_avatar
from backend.models.adventure_template import AdventureTemplate
from backend.models.avatar import Avatar
from backend.models.world_entity import WorldEntity, WorldScene
from backend.utils.path_security import (
    data_url_to_local_path,
    local_path_to_data_url,
)

logger = logging.getLogger(__name__)


_SAFE_SCENE_ID_RE = re.compile(r"^[A-Z0-9_]+$")


EDITOR_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


def _is_npc_entity(ent: WorldEntity) -> bool:
    return ent.entity_type == "NPC"


def _is_object_entity(ent: WorldEntity) -> bool:
    return ent.entity_type == "OBJECT"


OBJECT_ID_PATTERN = re.compile(r"^[A-Z0-9_]{1,30}$")


def _sanitize_object_id(raw_value: Optional[str], field_name: str) -> str:
    value = str(raw_value or "").strip()
    if not value:
        raise HTTPException(status_code=400, detail=f"{field_name} is required")
    if not OBJECT_ID_PATTERN.match(value):
        raise HTTPException(
            status_code=400,
            detail=f"{field_name} must contain only uppercase letters, digits, and underscores, and be at most 30 characters",
        )
    return value


def _sanitize_editor_id(raw_value: Optional[str], field_name: str) -> str:
    value = str(raw_value or "").strip()
    if not value:
        raise HTTPException(status_code=400, detail=f"{field_name} is required")
    if not EDITOR_ID_PATTERN.match(value):
        raise HTTPException(
            status_code=400,
            detail=f"{field_name} must match ^[A-Za-z0-9_-]{{1,128}}$",
        )
    return value


async def _get_owned_adventure_or_404(
    db: AsyncSession, template_id: str, user_id: str
) -> AdventureTemplate:
    adv = await db.get(AdventureTemplate, template_id)
    if not adv or adv.owner_id != user_id:
        raise HTTPException(status_code=404, detail="AdventureTemplate not found")
    return adv


async def _ensure_template_scene_exists(db: AsyncSession, template_id: str, scene_id: str) -> None:
    res = await db.execute(
        select(WorldScene).where(
            WorldScene.template_id == template_id,
            WorldScene.session_id.is_(None),
            WorldScene.id == scene_id,
        )
    )
    if not res.scalars().first():
        raise HTTPException(
            status_code=400, detail=f"scene_id '{scene_id}' does not exist in this adventure"
        )


def _normalize_lock_fields(
    *,
    code_to_unlock: Optional[str],
    item_to_unlock: Optional[str],
    rule_to_unlock: Optional[str],
) -> tuple[str, str, str]:
    code = str(code_to_unlock or "").strip()
    item = str(item_to_unlock or "").strip().upper()
    rule = str(rule_to_unlock or "").strip()

    if code:
        return code[:32], "", ""
    if item:
        from backend.utils.text_utils import slugify

        return "", slugify(item).upper().replace("-", "_")[:64], ""
    if rule:
        return "", "", rule[:500]
    return "", "", ""


def _public_data_to_local_path(path: str) -> Optional[str]:
    return data_url_to_local_path(path)


def _local_to_public_data_path(path: str) -> str:
    return local_path_to_data_url(path)


def _resolve_library_image_url(image_url: Optional[str]) -> Optional[str]:
    raw = str(image_url or "").strip()
    if not raw:
        return image_url

    local_path = _public_data_to_local_path(raw)
    if not local_path:
        return image_url

    if os.path.exists(local_path):
        return raw

    # Intentionally do not remap missing assets by basename across adventures.
    # Cross-adventure fallback causes confusing visuals when source adventures are deleted.
    return image_url


async def _get_template_avatar(db: AsyncSession, template_id: str) -> Optional[Avatar]:
    return await get_template_avatar(db, template_id)


async def _restore_missing_template_avatar(
    db: AsyncSession,
    template_id: str,
    adventure: AdventureTemplate,
) -> Optional[Avatar]:
    manifest = adventure.original_manifest if isinstance(adventure.original_manifest, dict) else {}
    prot = manifest.get("protagonist") if isinstance(manifest, dict) else None
    if not isinstance(prot, dict):
        return None

    image_url = str(prot.get("profile_image") or "").strip() or None
    if image_url:
        image_url = AdventureLogic.resolve_existing_data_asset_url(image_url) or image_url

    avatar = avatar_from_manifest(manifest, user_id=adventure.owner_id, template_id=template_id)
    avatar.profile_image = image_url
    db.add(avatar)
    await db.commit()
    return avatar
