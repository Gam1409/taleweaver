"""Publish an explicitly reviewed NPC and belongings in one database transaction."""

import hashlib
import json
from copy import deepcopy

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.routes.adventures.editing.common import (
    _ensure_template_scene_exists,
    _get_owned_adventure_or_404,
    _sanitize_object_id,
)
from backend.api.routes.adventures.editing.npc_drafts import (
    NpcCreateRequest,
    NpcDraft,
    NpcItemDraft,
    check_inner_layers,
)
from backend.core.auth import get_current_user
from backend.core.database import get_db
from backend.engine.authoring_concurrency import npc_publication_lease
from backend.engine.clothing.profiles import validate_profile
from backend.engine.clothing.schema import VisualProfile, WornItem
from backend.models.adventure_template import AdventureTemplate
from backend.models.user import User
from backend.models.world_entity import WorldEntity, WorldScene

router = APIRouter(tags=["Editor"])


def _item_record(item: WorldEntity) -> dict:
    return {
        "id": item.id,
        "name": item.name,
        "description": item.description,
        "item_type": item.item_type,
        "current_scene_id": "INVENTORY",
        "is_in_inventory": True,
        "is_portable": True,
        "wearable_slots": item.wearable_slots,
        "metadata_json": deepcopy(item.metadata_json),
    }


def _new_item(template_id: str, identifier: str, draft: NpcItemDraft) -> WorldEntity:
    metadata: dict = {}
    if draft.clothing:
        metadata["clothing"] = draft.clothing.model_dump()
    if draft.item_type == "READABLE":
        metadata["text_log_content"] = draft.text_log_content
        metadata["text_log_format"] = "DOCUMENT"
    return WorldEntity(
        id=identifier,
        template_id=template_id,
        session_id=None,
        entity_type="OBJECT",
        name=draft.name,
        description=draft.description,
        item_type=draft.item_type,
        current_scene_id="INVENTORY",
        is_in_inventory=True,
        is_portable=True,
        wearable_slots=list(draft.wearable_slots),
        metadata_json=metadata,
    )


def _new_npc(
    template_id: str,
    identifier: str,
    scene_id: str,
    draft: NpcDraft,
    items: list[WorldEntity],
    fingerprint: str,
) -> WorldEntity:
    profile = VisualProfile(
        appearance=draft.appearance,
        worn=[
            WornItem(item_id=item.id)
            for item, spec in zip(items, draft.items, strict=True)
            if spec.worn
        ],
    )
    validate_profile(profile, [_item_record(item) for item in items])
    return WorldEntity(
        id=identifier,
        template_id=template_id,
        session_id=None,
        entity_type="NPC",
        name=draft.name,
        description=draft.description,
        goal=draft.goal,
        character=draft.character,
        gender=draft.gender,
        age_years=draft.age_years,
        current_scene_id=scene_id,
        hp=draft.hp,
        max_hp=draft.hp,
        stamina=draft.stamina,
        max_stamina=draft.stamina,
        mana=draft.mana,
        max_mana=draft.mana,
        moveable=draft.moveable,
        movement_type="MOVABLE" if draft.moveable else "STATIONARY",
        is_killable=draft.is_killable,
        inventory=[item.id for item in items],
        visual_profile=profile.model_dump(),
        metadata_json={
            "personality_profile": draft.personality_profile.model_dump(),
            "authoring_draft_fingerprint": fingerprint,
        },
    )


def _sync_manifest(
    adventure: AdventureTemplate, npc: WorldEntity, items: list[WorldEntity]
) -> None:
    manifest = deepcopy(adventure.original_manifest or {})
    fields = (
        "id",
        "name",
        "description",
        "goal",
        "character",
        "gender",
        "age_years",
        "hp",
        "mana",
        "stamina",
        "moveable",
        "movement_type",
        "is_killable",
        "inventory",
        "visual_profile",
        "metadata_json",
        "current_scene_id",
    )
    manifest.setdefault("npcs", []).append({key: deepcopy(getattr(npc, key)) for key in fields})
    manifest.setdefault("objects", []).extend(_item_record(item) for item in items)
    adventure.original_manifest = manifest


@router.post("/{template_id}/editor/npc-with-items")
async def create_npc_with_items(
    template_id: str,
    payload: NpcCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    async with npc_publication_lease(template_id):
        return await _publish(template_id, payload, db, current_user)


async def _publish(
    template_id: str, payload: NpcCreateRequest, db: AsyncSession, current_user: User
) -> dict:
    adventure = await _get_owned_adventure_or_404(db, template_id, current_user.id)
    scene_id = _sanitize_object_id(payload.scene_id, "scene_id")
    await _ensure_template_scene_exists(db, template_id, scene_id)
    npc_id = "NPC_" + payload.creation_id.hex[:24].upper()
    fingerprint = hashlib.sha256(
        json.dumps(
            {"scene_id": scene_id, "draft": payload.draft.model_dump()},
            sort_keys=True,
            ensure_ascii=False,
        ).encode()
    ).hexdigest()
    rows = list(
        await db.scalars(
            select(WorldEntity).where(
                WorldEntity.template_id == template_id, WorldEntity.session_id.is_(None)
            )
        )
    )
    existing = next((row for row in rows if row.id == npc_id), None)
    if existing is not None:
        if (
            existing.entity_type == "NPC"
            and (existing.metadata_json or {}).get("authoring_draft_fingerprint") == fingerprint
        ):
            return {
                "status": "success",
                "npc_id": npc_id,
                "item_ids": list(existing.inventory or []),
            }
        raise HTTPException(
            409,
            "This NPC creation was already saved with different details. Reload the NPC list before creating another draft.",
        )
    draft = payload.draft
    check_inner_layers(
        adventure.original_manifest,
        draft,
        requested=any(bool(item.clothing and item.clothing.underwear) for item in draft.items),
    )
    items = [
        _new_item(template_id, f"ITEM_{payload.creation_id.hex[:20].upper()}_{index:02}", spec)
        for index, spec in enumerate(draft.items)
    ]
    identifiers = {npc_id, *(item.id for item in items)}
    scene_ids = set(
        await db.scalars(
            select(WorldScene.id).where(
                WorldScene.template_id == template_id, WorldScene.session_id.is_(None)
            )
        )
    )
    if identifiers.intersection({row.id for row in rows} | scene_ids):
        raise HTTPException(409, "An entity ID conflicts with this draft. Open a fresh NPC draft.")
    npc = _new_npc(template_id, npc_id, scene_id, draft, items, fingerprint)
    _sync_manifest(adventure, npc, items)
    db.add_all([npc, *items])
    await db.commit()
    return {"status": "success", "npc_id": npc_id, "item_ids": npc.inventory}
