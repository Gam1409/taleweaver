"""Nonblocking local-place backgrounds; no state or entity creation in image jobs."""

import asyncio
import logging
from uuid import uuid4

from sqlalchemy import or_, select, update

from backend.core import database, prompts
from backend.core.diagnostic_operations import diagnostic_job
from backend.engine.dynamic_locations.schema import policy, registry
from backend.engine.image_profiles import advanced_for, image_timeout
from backend.engine.image_prompt_adapter import asset_source
from backend.engine.media_engine import MediaEngine
from backend.engine.memory_rag.persistence import retry_transaction
from backend.engine.session_portraits import _settings
from backend.models.game_session import GameSession
from backend.models.session_state import SessionState
from backend.models.user import User
from backend.models.world_entity import WorldScene
from backend.utils.path_security import safe_data_path

logger = logging.getLogger(__name__)
_tasks: dict[tuple[str, str], asyncio.Task] = {}
_results: dict[tuple[str, str], str] = {}
_capacity = asyncio.Semaphore(1)


def status(session_id: str, scene_id: str, image: str | None) -> str:
    if image:
        return "ready"
    key = (session_id, scene_id)
    return "generating" if key in _tasks else _results.get(key, "missing")


async def _load(db, session_id, scene_id, user_id):
    state = await db.scalar(
        select(SessionState)
        .join(GameSession)
        .where(
            GameSession.id == session_id,
            GameSession.user_id == user_id,
        )
    )
    if state is None or scene_id not in registry(state).get("places", {}):
        return None, None
    scene = await db.scalar(
        select(WorldScene).where(
            WorldScene.session_id == session_id,
            WorldScene.id == scene_id,
        )
    )
    return state, scene


async def _generate(session_id: str, scene_id: str, user_id: str) -> bool:
    async with database.AsyncSessionLocal() as db:
        state, scene = await _load(db, session_id, scene_id, user_id)
        user = await db.get(User, user_id)
        if scene is None or user is None:
            return False
        if scene.image_url:
            return True
        t2i, style, tone = await _settings(db, state, user, "scene")
        role = "advanced" if advanced_for(t2i, "scene") else "simple"
        provider = (t2i.get(f"{role}_model_provider") or t2i.get("provider", "openai")).lower()
        options = {
            **t2i,
            "visual_target_type": "scene",
            "comfyui_profile": role,
            "_prompt_user": user,
            "_prompt_prepared": False,
        }
        for name in ("steps", "cfg_scale", "sampler_name", "scheduler"):
            options[name] = t2i.get(f"{role}_{name}")
        if provider in ("stable_diffusion", "ollama", "comfyui"):
            width, height = MediaEngine._resolve_sd_dimensions(
                "SCENE", t2i.get(f"{role}_min_long_edge")
            )
            options.update(width=width, height=height)
        facts = {"name": scene.label, "description": scene.description}
        prompt = asset_source(
            t2i, "scene", prompts.SCENE_IMAGE_PROMPT_TEMPLATE.format(**facts), **facts
        )
        if tone:
            prompt += " Mood: " + tone
        extension = "jpg" if (t2i.get("image_format") or "jpeg").lower() == "jpeg" else "png"
        keys = dict(user.encrypted_api_keys or {})
        source = (scene.pk, scene.label, scene.description)
        await db.commit()
        image = await asyncio.wait_for(
            MediaEngine.generate_image(
                prompt=prompt,
                provider=provider,
                model=t2i.get(f"{role}_model"),
                api_key=MediaEngine._resolve_api_key(provider, keys),
                adventure_id=session_id,
                target_dir=safe_data_path(
                    "adventures", "sessions", session_id, "visuals", "scenes"
                ),
                filename=f"{scene_id}_{uuid4().hex}.{extension}",
                provider_options=options,
                style_instruction=style,
            ),
            timeout=image_timeout(t2i),
        )
        if not image:
            raise ValueError("No background returned")
        return await _save_image(session_id, scene_id, user_id, source, image)


@retry_transaction
async def _save_image(
    session_id: str, scene_id: str, user_id: str, source: tuple, image: str
) -> bool:
    async with database.AsyncSessionLocal() as db:
        # A rewind, deletion, or changed scene must not receive an obsolete background.
        _state, current = await _load(db, session_id, scene_id, user_id)
        if current is None:
            return False
        if current.image_url:
            return True
        if (current.pk, current.label, current.description) != source:
            return False
        saved = await db.execute(
            update(WorldScene)
            .where(
                WorldScene.pk == source[0],
                WorldScene.session_id == session_id,
                WorldScene.label == source[1],
                WorldScene.description == source[2],
                or_(WorldScene.image_url.is_(None), WorldScene.image_url == ""),
            )
            .values(image_url=image)
            .execution_options(synchronize_session=False)
        )
        await db.commit()
        return saved.rowcount == 1


@diagnostic_job("scene_background")
async def _run(session_id, scene_id, user_id):
    key = (session_id, scene_id)
    try:
        async with _capacity:
            saved = await _generate(session_id, scene_id, user_id)
        _results[key] = "ready" if saved else "missing"
    except asyncio.CancelledError:
        _results[key] = "interrupted"
        raise
    except Exception:
        _results[key] = "failed"
        logger.exception("Dynamic location image failed for %s/%s", session_id, scene_id)
    finally:
        _tasks.pop(key, None)
        while len(_results) > 256:
            _results.pop(next(iter(_results)))


def schedule(session_id, scene_id, user_id):
    key = (session_id, scene_id)
    if key not in _tasks:
        _tasks[key] = asyncio.create_task(_run(session_id, scene_id, user_id))


def schedule_images(state, user_id, ids):
    if policy(state).generate_images:
        for scene_id in ids:
            if scene_id in registry(state).get("places", {}):
                schedule(state.session_id, scene_id, user_id)


async def shutdown():
    tasks = list(_tasks.values())
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
