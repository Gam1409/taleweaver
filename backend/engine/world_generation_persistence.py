"""Persist generated narrative and load existing assets for cover generation."""

from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.llm_logger import log_structured_event
from backend.engine.authoring_settings import preserve_authoring_settings
from backend.engine.clothing.settings import preserve_clothing_settings
from backend.engine.npc_cards.settings import preserve_card_settings
from backend.engine.nsfw.settings import preserve_nsfw_settings
from backend.engine.template_avatar import get_template_avatar
from backend.models.adventure_template import AdventureTemplate


async def persist_generated_narrative(
    db: AsyncSession,
    adventure: AdventureTemplate | None,
    template_id: str,
    manifest_dict: dict[str, Any],
    original_prompt: str,
    language: str | None,
    status_callback: Callable[[str], Awaitable[None]] | None,
) -> None:
    from backend.engine.world_generator import _publish_generation_status_with_callback

    # 2. Update Status + persist narrative fields
    if adventure:
        await db.refresh(adventure)
        await _publish_generation_status_with_callback(
            db, adventure, "Building Scenes & Plot...", status_callback=status_callback
        )
        log_structured_event(
            "adventure.generation.status",
            template_id=template_id,
            status=adventure.creation_status,
            phase="apply_manifest",
        )
        adventure.teaser = manifest_dict.get("teaser") or ""
        adventure.original_prompt = original_prompt
        if language:
            adventure.language = language
        if not adventure.origin_id:
            adventure.origin_id = manifest_dict.get("origin_id") or template_id
        if not adventure.original_manifest or set(adventure.original_manifest) <= {
            "visual_presets",
            "visual_preset_source",
            "npc_card_settings",
            "clothing_settings",
            "nsfw_settings",
            "narrator_settings",
            "world_brief",
            "world_brief_sources",
        }:
            from backend.engine.story_visual_presets import preserve_story_presets

            adventure.original_manifest = preserve_authoring_settings(
                preserve_nsfw_settings(
                    preserve_clothing_settings(
                        preserve_card_settings(
                            preserve_story_presets(manifest_dict, adventure), adventure
                        ),
                        adventure,
                    ),
                    adventure,
                ),
                adventure,
            )
        from backend.engine.generation_control import guard_generation_write

        await guard_generation_write(db, adventure)
        await db.commit()


async def load_cover_source_assets(
    db: AsyncSession, cover_source_adventure_id: str | None, allow_reuse_source_assets: bool
) -> dict[str, Any] | None:
    # Load source assets for cover-mode image reuse
    cover_source_assets = None
    if allow_reuse_source_assets and cover_source_adventure_id:
        from backend.models.world_entity import WorldEntity, WorldScene  # noqa: PLC0415

        src_adv = await db.get(AdventureTemplate, cover_source_adventure_id)
        if src_adv:
            src_avatar = await get_template_avatar(db, cover_source_adventure_id)
            src_scene_res = await db.execute(
                select(WorldScene).where(WorldScene.template_id == cover_source_adventure_id)
            )
            src_scenes = [
                s for s in src_scene_res.scalars().all() if getattr(s, "session_id", None) is None
            ]
            src_entity_res = await db.execute(
                select(WorldEntity).where(WorldEntity.template_id == cover_source_adventure_id)
            )
            src_entities = [
                e for e in src_entity_res.scalars().all() if getattr(e, "session_id", None) is None
            ]
            cover_source_assets = {
                "cover": src_adv.image_url,
                "protagonist": {
                    "id": "PROTAGONIST",
                    "name": (src_avatar.name if src_avatar else ""),
                    "image_url": (src_avatar.profile_image if src_avatar else None),
                },
                "scenes": [
                    {"id": s.id, "name": s.label, "image_url": s.image_url} for s in src_scenes
                ],
                "npcs": [
                    {"id": e.id, "name": e.name, "image_url": e.image_url}
                    for e in src_entities
                    if e.entity_type == "NPC"
                ],
                "objects": [
                    {"id": e.id, "name": e.name, "image_url": e.image_url}
                    for e in src_entities
                    if e.entity_type == "OBJECT"
                ],
            }

    return cover_source_assets
