"""Keep the existing manifest topology consistent with authored scene deletion."""

from copy import deepcopy
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.engine.world_location_fields import scene_fields
from backend.models.adventure_template import AdventureTemplate
from backend.models.world_entity import WorldEntity, WorldScene


def _definitions(manifest: dict[str, Any], key: str) -> list[dict[str, Any]]:
    values = manifest.get(key)
    return (
        [value for value in values if isinstance(value, dict)] if isinstance(values, list) else []
    )


async def sync_deleted_scene_manifest(db: AsyncSession, adventure: AdventureTemplate) -> None:
    """An initialized world may be empty; lazy repair must not replay deleted topology."""
    scenes = list(
        await db.scalars(
            select(WorldScene)
            .where(WorldScene.template_id == adventure.id, WorldScene.session_id.is_(None))
            .order_by(WorldScene.pk)
        )
    )
    scene_ids = {scene.id for scene in scenes}
    entity_ids = set(
        await db.scalars(
            select(WorldEntity.id).where(
                WorldEntity.template_id == adventure.id, WorldEntity.session_id.is_(None)
            )
        )
    )
    manifest = deepcopy(adventure.original_manifest or {})
    definitions = [
        scene for scene in _definitions(manifest, "scenes") if scene.get("id") in scene_ids
    ]
    defined_ids = {scene["id"] for scene in definitions}
    definitions.extend(scene_fields(scene) for scene in scenes if scene.id not in defined_ids)
    manifest["scenes"] = definitions
    for key in ("npcs", "objects"):
        if key in manifest:
            manifest[key] = [
                entity for entity in _definitions(manifest, key) if entity.get("id") in entity_ids
            ]
    if "exits" in manifest:
        manifest["exits"] = [
            edge
            for edge in _definitions(manifest, "exits")
            if edge.get("from_scene_id") in scene_ids and edge.get("to_scene_id") in scene_ids
        ]
    start = manifest.get("start_scene_id")
    if start and start not in scene_ids:
        if scenes:
            manifest["start_scene_id"] = scenes[0].id
        else:
            manifest.pop("start_scene_id", None)
    adventure.original_manifest = manifest
