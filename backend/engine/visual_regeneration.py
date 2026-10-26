"""Regenerate one owned visual with a common profile and optional local reference."""

from fastapi import HTTPException
from sqlalchemy import inspect, select, update

from backend.core import database
from backend.core.comfyui_config import prompt_rules
from backend.core.style_catalog import resolve_style_instruction, resolve_tone_instruction
from backend.engine.image_profiles import advanced_for
from backend.engine.media_engine import MediaEngine
from backend.engine.memory_rag.persistence import retry_transaction
from backend.engine.story_visual_presets import story_t2i
from backend.models.adventure_template import AdventureTemplate
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
    source = _source(adventure, target, field)
    template_id, user_id = adventure.id, user.id
    # No transaction or write lock is retained while a remote provider runs.
    await db.commit()
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
    await _save_visual(template_id, user_id, payload, source, image_url)
    return {"status": "success", "image_url": image_url}


def _source(adventure, target, field: str) -> dict:
    return {
        "identity": inspect(target).identity,
        "updated_at": target.updated_at,
        "image": getattr(target, field),
        "template_updated_at": adventure.updated_at,
    }


@retry_transaction
async def _save_visual(
    template_id: str, user_id: str, payload, source: dict, image_url: str
) -> None:
    async with database.AsyncSessionLocal() as db:
        adventure = await db.get(AdventureTemplate, template_id)
        if adventure is None or adventure.owner_id != user_id:
            raise HTTPException(404, "Adventure template not found.")
        target, field = await _target(db, adventure, payload)
        if _source(adventure, target, field) != source:
            raise HTTPException(
                409, "The visual target changed while generating. The current image was kept."
            )
        model = type(target)
        primary_keys = inspect(model).primary_key
        owned = (
            select(AdventureTemplate.id)
            .where(
                AdventureTemplate.id == template_id,
                AdventureTemplate.owner_id == user_id,
                AdventureTemplate.updated_at == source["template_updated_at"],
            )
            .exists()
        )
        changed = await db.execute(
            update(model)
            .where(
                *(
                    column == value
                    for column, value in zip(primary_keys, source["identity"], strict=True)
                ),
                model.updated_at == source["updated_at"],
                getattr(model, field) == source["image"],
                owned,
            )
            .values(**{field: image_url})
            .execution_options(synchronize_session=False)
        )
        if changed.rowcount != 1:
            raise HTTPException(
                409, "The visual target changed while saving. The current image was kept."
            )
        await db.commit()


async def _generate_target(payload, target, prompt: str, common: dict):
    if payload.target_type == "scene":
        return await MediaEngine.generate_scene_image(prompt=prompt, **common)
    return await MediaEngine.generate_entity_image(
        prompt=prompt, entity_id=target.id, entity_type=payload.target_type.upper(), **common
    )
