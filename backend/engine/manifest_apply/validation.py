"""Validate world references before modifying persistent entities."""

from typing import Any


def validate_world_references(manifest: dict[str, Any]) -> None:
    scenes = manifest.get("scenes", [])
    scene_ids = {scene["id"] for scene in scenes}
    if len(scene_ids) != len(scenes):
        raise ValueError("Scene IDs must be unique.")
    for scene in scenes:
        if not scene.get("id"):
            raise ValueError("Every scene requires an ID.")
    for exit_def in manifest.get("exits", []):
        if any(exit_def.get(key) not in scene_ids for key in ("from_scene_id", "to_scene_id")):
            raise ValueError("An exit references a scene that does not exist.")
    for npc in manifest.get("npcs", []):
        if not npc.get("id") or not npc.get("name"):
            raise ValueError("Every NPC requires an ID.")
        scene_id = npc.get("start_scene_id") or npc.get("current_scene_id") or npc.get("scene_id")
        if scene_id and scene_id not in scene_ids:
            raise ValueError("An NPC references a scene that does not exist.")
