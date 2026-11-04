"""Regenerate portraits for session-owned NPCs without restarting their adventure."""

import asyncio
import json
from copy import deepcopy
from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

from fastapi import HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import CursorResult, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import set_attribute, set_committed_value

from backend.core import database, prompts
from backend.core.comfyui_config import select_workflow
from backend.core.image_purposes import image_provider
from backend.core.style_catalog import resolve_style_instruction, resolve_tone_instruction
from backend.core.visual_trace import traced
from backend.engine.character_identity import describe_character
from backend.engine.clothing.frames import compose_frame, extract_frame
from backend.engine.clothing.visuals import npc_visuals, portrait_description
from backend.engine.image_profiles import advanced_for, image_timeout, validate_image_profiles
from backend.engine.image_prompt_adapter import asset_source
from backend.engine.media_engine import MediaEngine
from backend.engine.memory_rag.persistence import retry_transaction
from backend.engine.npc_journal.records import memory_context
from backend.engine.story_visual_presets import story_t2i
from backend.models.adventure_template import AdventureTemplate
from backend.models.game_session import GameSession
from backend.models.session_state import SessionState
from backend.models.user import User
from backend.models.world_entity import WorldEntity
from backend.utils.path_security import safe_data_path, sanitize_path_component


class SessionPortraitRequest(BaseModel):
    target_id: str = Field(min_length=1, max_length=128)
    use_previous_image: bool = False
    change_description: str = Field(default="", max_length=1000)


async def _context(
    db: AsyncSession, session_id: str, target_id: str, user_id: str
) -> tuple[SessionState, WorldEntity]:
    query = (
        select(SessionState)
        .join(GameSession, GameSession.id == SessionState.session_id)
        .where(GameSession.id == session_id, GameSession.user_id == user_id)
        .execution_options(populate_existing=True)
    )
    state = (await db.execute(query)).scalar_one_or_none()
    if not state:
        raise HTTPException(404, "Session not found.")
    npc_query = (
        select(WorldEntity)
        .where(
            WorldEntity.session_id == session_id,
            WorldEntity.id == target_id,
            WorldEntity.entity_type.in_(["NPC", "npc"]),
        )
        .execution_options(populate_existing=True)
    )
    npc = (await db.execute(npc_query)).scalar_one_or_none()
    if not npc:
        raise HTTPException(404, "NPC not found in this session.")
    return state, npc


def _override_key(state: SessionState, target_id: str) -> str:
    return next(
        (key for key in (state.entity_states or {}) if key.strip().upper() == target_id.upper()),
        target_id,
    )


async def _settings(
    db: AsyncSession, state: SessionState, user: User, kind: str = "npc"
) -> tuple[dict, str, str]:
    raw = (state.entity_states or {}).get("__manifest_snapshot__")
    snapshot = raw if isinstance(raw, dict) else {}
    story: Any = SimpleNamespace(original_manifest=snapshot.get("original_manifest") or {})
    if not snapshot and state.template_id:
        story = await db.get(AdventureTemplate, state.template_id) or story
    t2i = story_t2i(user.t2i_settings, story)
    validate_image_profiles(
        SimpleNamespace(t2i_settings=t2i, encrypted_api_keys=user.encrypted_api_keys), [kind]
    )
    meta = snapshot.get("adventure") or {}
    styles = state.selected_image_styles
    tone = state.selected_tone
    return (
        t2i,
        resolve_style_instruction(
            styles if styles is not None else meta.get("selected_image_styles"),
            user.image_styles_catalog or [],
        ),
        resolve_tone_instruction(
            tone if tone is not None else meta.get("selected_tone"), user.tone_catalog or []
        ),
    )


def _image_request(
    session_id: str, npc: dict, t2i: dict, user: User, style: str, tone: str
) -> dict:
    profile = "advanced" if advanced_for(t2i, "npc") else "simple"
    provider = image_provider(t2i, profile, "npc")
    options = {
        **t2i,
        "image_purpose": "npc",
        "visual_target_type": "npc",
        "_prompt_user": user,
        "comfyui_profile": profile,
        "_prompt_prepared": False,
        **{
            key: t2i.get(f"{profile}_{key}")
            for key in ("steps", "cfg_scale", "sampler_name", "scheduler")
        },
    }
    if provider in ("stable_diffusion", "ollama", "comfyui"):
        width, height = MediaEngine._resolve_sd_dimensions(
            "NPC", t2i.get(f"{profile}_min_long_edge")
        )
        options.update(width=width, height=height)
    prompt = asset_source(t2i, "npc", prompts.NPC_IMAGE_PROMPT_TEMPLATE.format(**npc), **npc)
    if tone:
        prompt += f" Mood: {tone}"
    ext = "jpg" if (t2i.get("image_format") or "jpeg").lower() == "jpeg" else "png"
    return {
        "prompt": prompt,
        "model": t2i.get(f"{profile}_model"),
        "provider": provider,
        "api_key": MediaEngine._resolve_api_key(provider, user.encrypted_api_keys or {}),
        "adventure_id": session_id,
        "target_dir": safe_data_path("adventures", "sessions", session_id, "visuals", "entities"),
        "filename": f"npc_{uuid4().hex}.{ext}",
        "provider_options": options,
        "style_instruction": style,
    }


@retry_transaction
async def _try_save_portrait(
    session_id: str, target_id: str, user_id: str, image_url: str, token: str
) -> bool:
    # A fresh transaction checks ownership and merges only the image field.
    async with database.AsyncSessionLocal() as db:
        state, npc = await _context(db, session_id, target_id, user_id)
        if (state.entity_states or {}).get("__portrait_requests__", {}).get(target_id) != token:
            raise HTTPException(
                409, "The portrait request is no longer current. The image was not applied."
            )
        key = _override_key(state, target_id)
        before = deepcopy(state.entity_states)
        overrides = deepcopy(before or {})
        override = overrides.get(key)
        if isinstance(override, dict) and "image_url" in override:
            override["image_url"] = image_url
        overrides["__portrait_requests__"].pop(target_id, None)
        updated = await db.execute(
            update(SessionState)
            .where(SessionState.id == state.id, SessionState.entity_states == before)
            .values(entity_states=overrides)
            .execution_options(synchronize_session=False)
        )
        if cast(CursorResult[Any], updated).rowcount != 1:
            return False
        set_attribute(npc, "image_url", image_url)
        await db.commit()
        return True


async def _save_portrait(
    session_id: str, target_id: str, user_id: str, image_url: str, token: str
) -> None:
    for _attempt in range(3):
        if await _try_save_portrait(session_id, target_id, user_id, image_url, token):
            return
    raise HTTPException(409, "The session changed while saving the portrait. Try again.")


async def _portrait_facts(
    db: AsyncSession, state: SessionState, npc: WorldEntity, override: dict
) -> tuple[dict, dict | None]:
    visible = await npc_visuals(db, state, npc)
    if visible is not None:
        return {"name": visible["name"], "description": portrait_description(visible)}, visible
    facts = {key: override.get(key, getattr(npc, key)) for key in ("name", "description")}
    facts["description"] = describe_character(npc, facts.get("description")) + memory_context(
        npc, visual_only=True
    )
    return facts, None


async def _portrait_change(user: User, change: str, visible: dict | None) -> str:
    if visible is None:
        return change
    frame = await extract_frame(user, change, [visible])
    return json.dumps(compose_frame(frame, [visible]), ensure_ascii=False)


async def _reserve_portrait(db: AsyncSession, state: SessionState, target_id: str) -> str:
    token = str(uuid4())
    before = deepcopy(state.entity_states)
    reserved = deepcopy(before or {})
    reserved.setdefault("__portrait_requests__", {})[target_id] = token
    updated = await db.execute(
        update(SessionState)
        .where(SessionState.id == state.id, SessionState.entity_states == before)
        .values(entity_states=reserved)
        .execution_options(synchronize_session=False)
    )
    if cast(CursorResult[Any], updated).rowcount != 1:
        raise HTTPException(409, "The session changed before portrait generation. Try again.")
    await db.commit()
    set_committed_value(state, "entity_states", reserved)
    return token


@traced
async def regenerate_session_portrait(
    session_id: str, payload: SessionPortraitRequest, db: AsyncSession, user: User
) -> dict:
    if sanitize_path_component(session_id) != session_id:
        raise HTTPException(404, "Session not found.")
    state, npc = await _context(db, session_id, payload.target_id, user.id)
    raw_override = (state.entity_states or {}).get(_override_key(state, npc.id))
    override = raw_override if isinstance(raw_override, dict) else {}
    facts, visible = await _portrait_facts(db, state, npc, override)
    token = await _reserve_portrait(db, state, payload.target_id)
    try:
        t2i, style, tone = await _settings(db, state, user)
        request = _image_request(session_id, facts, t2i, user, style, tone)
        if payload.change_description.strip():
            request["prompt"] += (
                " Requested portrait change (preserve identity and single-subject framing): "
                + await _portrait_change(user, payload.change_description.strip(), visible)
            )
        if payload.use_previous_image:
            if request["provider"] != "comfyui":
                raise ValueError("Previous portrait references currently require ComfyUI.")
            previous = override.get("image_url", npc.image_url)
            if not previous:
                raise ValueError("This NPC has no previous portrait to use as a reference.")
            select_workflow(request["provider_options"], reference=True)
            request["provider_options"]["reference_image_url"] = previous
            request["prompt"] += (
                " Preserve the reference character's identity, facial features and appearance; "
                "change only the requested expression, action or setting."
            )
            if visible is not None:
                request["prompt"] += (
                    " Use the supplied current visible clothing only; the reference provides "
                    "facial identity, not a previous outfit."
                )
        user_id = user.id
        # Release the read transaction while the provider is working.
        await db.commit()
        image_url = await asyncio.wait_for(
            MediaEngine.generate_image(**request), timeout=image_timeout(t2i)
        )
        if not image_url:
            raise HTTPException(502, "No portrait was returned. The previous image was kept.")
        await _save_portrait(session_id, payload.target_id, user_id, image_url, token)
    except TimeoutError as exc:
        raise HTTPException(
            504,
            "Portrait generation timed out. The previous image was kept; a remote job may still be running.",
        ) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"status": "success", "image_url": image_url, "target_id": payload.target_id}
