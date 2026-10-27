"""Restore a blueprint and its initial world without creating a game session."""

import os

from backend.core.config import settings
from backend.core.game_modes import mode_policy, normalize_vn_template
from backend.engine.import_build_blueprint_template import build_blueprint_template
from backend.engine.world_generator import WorldGenerator


async def restore_blueprint(db, payload, user, owner_id, origin_id):
    manifest = payload.get("original_manifest") or payload.get("manifest") or payload
    adv_meta = payload.get("adventure") or payload

    enforcement_mode = (
        adv_meta.get("rule_enforcement_mode") or manifest.get("rule_enforcement_mode") or "rpg"
    )
    is_strict = mode_policy(
        enforcement_mode, adv_meta.get("strict_rules", manifest.get("strict_rules"))
    ).mechanics

    new_template = build_blueprint_template(
        payload, manifest, adv_meta, owner_id, origin_id, enforcement_mode, is_strict
    )

    normalize_vn_template(new_template)
    db.add(new_template)
    await db.flush()

    if not new_template.image_url:
        from backend.engine.media_engine import MediaEngine

        new_template.image_url = await MediaEngine.generate_placeholder(
            new_template.id,
            new_template.title,
            os.path.join(settings.DATA_DIR, "adventures", "library", new_template.id),
            category="COVER",
        )
        await db.flush()

    # Prepare manifest for apply_manifest to ensure protagonist has starting items
    if "protagonist" in manifest:
        p = manifest["protagonist"]
        if "starting_inventory" not in p:
            p["starting_inventory"] = p.get("inventory", [])
        if "starting_equipment" not in p:
            p["starting_equipment"] = p.get("equipment", {})

    default_scene_id = (
        manifest.get("scenes", [{}])[0].get("id") if manifest.get("scenes") else "START"
    )
    for n in manifest.get("npcs", []):
        if "start_scene_id" not in n:
            n["start_scene_id"] = n.get("current_scene_id") or n.get("scene_id") or default_scene_id
    for o in manifest.get("objects", []):
        if "start_scene_id" not in o:
            o["start_scene_id"] = o.get("current_scene_id") or o.get("scene_id") or default_scene_id

    await WorldGenerator.apply_manifest(db, new_template.id, manifest, user=user)

    # Imports populate world data directly; mark template as fully ready.
    new_template.is_ready = True
    new_template.creation_status = "Ready"
    new_template.creation_error = None
    await db.commit()
    # Ensure thumbnails are generated for imported assets
    from backend.engine.media_engine import MediaEngine

    await MediaEngine.ensure_thumbnails(new_template.id)
    return True
