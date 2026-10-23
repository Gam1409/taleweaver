"""Regenerate one owned visual with a common profile and optional local reference."""

from fastapi import HTTPException
from sqlalchemy import select

from backend.core.comfyui_config import prompt_rules
from backend.core.style_catalog import resolve_style_instruction, resolve_tone_instruction
from backend.engine.image_profiles import advanced_for
from backend.engine.media_engine import MediaEngine
from backend.engine.story_visual_presets import story_t2i
from backend.models.avatar import Avatar
from backend.models.world_entity import WorldEntity, WorldScene
from backend.utils.path_security import (
    data_url_to_local_path,
    ensure_within_base_dir,
    safe_data_path,
)


async def _target(db, adventure, payload):
    if payload.target_type == "cover":
        return adventure, "image_url"
    if payload.target_type == "protagonist":
        query = (
            select(Avatar)
            .where(Avatar.template_id == adventure.id)
            .order_by(Avatar.created_at, Avatar.id)
            .limit(1)
        )
        field = "profile_image"
    else:
        model = WorldScene if payload.target_type == "scene" else WorldEntity
        query = select(model).where(
            model.template_id == adventure.id, model.id == payload.target_id
        )
        field = "image_url"
    target = (await db.execute(query)).scalars().first()
    if not target:
        raise HTTPException(404, "Visual target not found.")
    return target, field


def _reference_options(t2i: dict, target, field: str, template_id: str, advanced: bool) -> dict:
    profile = "advanced" if advanced else "simple"
    if t2i.get(f"{profile}_model_provider") != "comfyui":
        raise ValueError("Using the current image requires a ComfyUI image workflow.")
    url = getattr(target, field, None)
    path = data_url_to_local_path(url) if url else None
    if not path:
        raise ValueError("No local image is available as a reference.")
    ensure_within_base_dir(path, safe_data_path("adventures", "library", template_id))
    return {**t2i, "reference_image_url": url}


async def regenerate_owned_visual(db, adventure, user, payload) -> dict:
    from backend.api.routes.adventures.assets import _build_visual_prompt

    target, field = await _target(db, adventure, payload)
    t2i = story_t2i(user.t2i_settings, adventure)
    t2i["_prompt_prepared"] = bool(payload.prompt and payload.prompt.strip())
    advanced = advanced_for(t2i, payload.target_type, payload.use_advanced_model)
    if payload.use_current_image:
        t2i = _reference_options(t2i, target, field, adventure.id, advanced)
    style = resolve_style_instruction(adventure.selected_image_styles, user.image_styles_catalog)
    common = {
        "adventure_id": adventure.id,
        "user_config": {"t2i_settings": t2i, "prompt_user": user},
        "api_keys": user.encrypted_api_keys or {},
        "style_instruction": style,
        "use_advanced_model": advanced,
    }
    if payload.target_type == "cover":
        image_url = await MediaEngine.generate_adventure_cover(
            title=adventure.title,
            original_prompt=payload.prompt or adventure.original_prompt or "",
            **common,
        )
    else:
        prompt = _build_visual_prompt(
            payload.target_type,
            target,
            payload.prompt,
            style_instruction=style,
            tone_instruction=resolve_tone_instruction(adventure.selected_tone, user.tone_catalog),
        )
        role = "advanced" if advanced else "simple"
        if (
            not t2i["_prompt_prepared"]
            and t2i.get(f"{role}_model_provider") == "comfyui"
            and prompt_rules({**t2i, "comfyui_profile": role})
        ):
            prompt = f"{payload.target_type}: {getattr(target, 'name', None) or getattr(target, 'label', '')}. {getattr(target, 'description', '')}"
            tone = resolve_tone_instruction(adventure.selected_tone, user.tone_catalog)
            if tone:
                prompt += f" Mood: {tone}"
        image_url = await _generate_target(payload, target, prompt, common)
    if not image_url:
        raise ValueError("The image provider returned no image. The previous image was kept.")
    setattr(target, field, image_url)
    await db.commit()
    return {"status": "success", "image_url": image_url}


async def _generate_target(payload, target, prompt: str, common: dict):
    if payload.target_type == "scene":
        return await MediaEngine.generate_scene_image(prompt=prompt, **common)
    return await MediaEngine.generate_entity_image(
        prompt=prompt, entity_id=target.id, entity_type=payload.target_type.upper(), **common
    )
