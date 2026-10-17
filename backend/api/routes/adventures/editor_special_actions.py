"""Editor endpoint for configuring special attacks on the protagonist and on NPCs."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from backend.api.routes.adventures.editor import (
    _get_owned_adventure_or_404,
    _get_template_avatar,
    _sanitize_editor_id,
)
from backend.core.auth import get_current_user
from backend.core.database import get_db
from backend.engine.world_schemas import SpecialActionSchema
from backend.models.adventure_template import AdventureTemplate
from backend.models.user import User
from backend.models.world_entity import WorldEntity

router = APIRouter(tags=["Editor"])

MAX_SPECIAL_ACTIONS = 8


class SpecialActionsUpdateRequest(BaseModel):
    target_type: Literal["protagonist", "npc"]
    target_id: str
    special_actions: list[SpecialActionSchema] = Field(
        default_factory=list, max_length=MAX_SPECIAL_ACTIONS
    )


def _serialize_actions(actions: list[SpecialActionSchema]) -> list[dict[str, Any]]:
    serialized = []
    seen: set[str] = set()
    for action in actions:
        action_id = _sanitize_editor_id(action.id.strip().upper(), "special action id")
        if action_id in seen:
            raise HTTPException(status_code=400, detail=f"Duplicate special action id: {action_id}")
        seen.add(action_id)
        serialized.append({**action.model_dump(exclude_none=True), "id": action_id})
    return serialized


def _update_manifest(
    adv: AdventureTemplate, target_type: str, target_id: str, actions: list[dict[str, Any]]
) -> None:
    if not isinstance(adv.original_manifest, dict):
        return
    manifest = deepcopy(adv.original_manifest)
    if target_type == "protagonist" and isinstance(manifest.get("protagonist"), dict):
        manifest["protagonist"]["special_actions"] = actions
    for npc in manifest.get("npcs") or []:
        if target_type == "npc" and isinstance(npc, dict) and npc.get("id") == target_id:
            npc["special_actions"] = actions
    adv.original_manifest = manifest
    flag_modified(adv, "original_manifest")


async def _save_protagonist_actions(
    db: AsyncSession, template_id: str, actions: list[dict[str, Any]]
) -> None:
    avatar = await _get_template_avatar(db, template_id)
    if not avatar:
        raise HTTPException(status_code=404, detail="Protagonist not found")
    stats = dict(avatar.stats or {})
    stats["special_actions"] = actions
    stats["unlocked_actions"] = [a["id"] for a in actions if not a.get("is_locked")]
    avatar.stats = stats
    flag_modified(avatar, "stats")


async def _save_npc_actions(
    db: AsyncSession, template_id: str, npc_id: str, actions: list[dict[str, Any]]
) -> None:
    res = await db.execute(
        select(WorldEntity).where(
            WorldEntity.template_id == template_id,
            WorldEntity.session_id.is_(None),
            WorldEntity.entity_type == "NPC",
            WorldEntity.id == npc_id,
        )
    )
    npc = res.scalars().first()
    if not npc:
        raise HTTPException(status_code=404, detail="NPC not found")
    metadata = dict(npc.metadata_json or {})
    metadata["special_actions"] = actions
    npc.metadata_json = metadata
    flag_modified(npc, "metadata_json")


@router.put("/{template_id}/editor/special-actions")
async def update_special_actions(
    template_id: str,
    payload: SpecialActionsUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Replaces the special attacks of the protagonist or of one NPC."""
    adv = await _get_owned_adventure_or_404(db, template_id, current_user.id)
    target_id = _sanitize_editor_id(payload.target_id, "target_id")
    actions = _serialize_actions(payload.special_actions)

    if payload.target_type == "protagonist":
        await _save_protagonist_actions(db, template_id, actions)
    else:
        await _save_npc_actions(db, template_id, target_id, actions)
    _update_manifest(adv, payload.target_type, target_id, actions)
    await db.commit()
    return {"status": "success", "special_actions": actions}
