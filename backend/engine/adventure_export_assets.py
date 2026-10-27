"""Read-only inventory normalization and archive asset localization for export."""

import logging
import os
from typing import Any

from backend.models.world_entity import WorldExit, WorldScene
from backend.utils.path_security import data_url_to_local_path

logger = logging.getLogger(__name__)


def normalize_exported_equipment(avatar, entities):
    # Normalize legacy avatar inventory/equipment to ID references for the manifest.
    # NOTE: This must NOT mutate the database — exporting is a read-only operation.
    # Mutating during export causes "database is locked" errors on SQLite when
    # background tasks (e.g. world generation) hold a write lock. We compute
    # the cleaned values locally and use them when building the manifest below.
    local_final_inventory: list[str] = []
    local_final_equipment: dict[str, str] = {}
    if avatar:
        cleaned_inventory, cleaned_equipment = _clean_avatar_item_references(avatar)

        # Priority deduplication: Scene > Inventory > Equipped
        items_in_scene = set()
        for ent in entities:
            if (
                ent.entity_type == "OBJECT"
                and ent.current_scene_id
                and ent.current_scene_id != "INVENTORY"
            ):
                items_in_scene.add(ent.id)

        for item_id in cleaned_inventory:
            if item_id in items_in_scene:
                continue
            if item_id not in local_final_inventory:
                local_final_inventory.append(item_id)

        for slot, item_id in cleaned_equipment.items():
            if (
                item_id in items_in_scene
                or item_id in local_final_inventory
                or item_id in local_final_equipment.values()
            ):
                continue
            local_final_equipment[slot] = item_id

    return local_final_inventory, local_final_equipment


def serialize_world_location(obj):
    from backend.engine.adventure_exporter import _SYSTEM_ENTITY_KEYS

    if not obj:
        return None
    data = {
        c.name: getattr(obj, c.name)
        for c in obj.__table__.columns
        if c.name not in _SYSTEM_ENTITY_KEYS
    }
    if isinstance(obj, WorldScene):
        decor = data.get("decorative_objects")
        if not isinstance(decor, list):
            decor = []
        data["decorative_objects"] = [str(d) for d in decor if isinstance(d, (str, int, float))]
    if isinstance(obj, WorldExit):
        exit_type = str(getattr(obj, "exit_type", "one_way") or "one_way").strip().lower()
        data["exit_type"] = exit_type
        data["is_bidirectional"] = exit_type == "bidirectional"
    return data


def localize_archive_asset(path, adventure_dir, asset_mapping):
    from backend.engine.adventure_exporter import _ensure_within_data_dir, _safe_zip_asset_name

    if not path or not path.startswith("/data/"):
        return path

    local_full = data_url_to_local_path(path)
    if not local_full:
        logger.warning("Skipping unsafe asset path during ADZ export: %s", path)
        return path

    if os.path.exists(local_full):
        fname = _safe_zip_asset_name(local_full)
        zip_rel = f"assets/{fname}"
        asset_mapping[local_full] = zip_rel
        return zip_rel

    # Fallback: search in adventure_dir if not found directly
    # (handles cases where path might be different but file exists there)
    fname = _safe_zip_asset_name(path)
    for root, _dirs, files in os.walk(adventure_dir):
        if fname in files:
            local_full = _ensure_within_data_dir(os.path.join(root, fname))
            zip_rel = f"assets/{fname}"
            asset_mapping[local_full] = zip_rel
            return zip_rel

    return path


def _clean_avatar_item_references(avatar):
    def _normalize_item(item: Any) -> str | None:
        if isinstance(item, dict):
            return item.get("id")
        return item

    cleaned_inventory: list[str] = []
    for item in avatar.inventory or []:
        item_id = _normalize_item(item)
        if item_id:
            cleaned_inventory.append(item_id)

    cleaned_equipment: dict[str, str] = {}
    for slot, item in (avatar.equipment or {}).items():
        item_id = _normalize_item(item)
        if item_id:
            cleaned_equipment[slot] = item_id

    return cleaned_inventory, cleaned_equipment
