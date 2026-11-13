"""Read-only inventory normalization and archive asset localization for export."""

import hashlib
import logging
import os
from collections.abc import Sequence
from typing import Any

from backend.engine.export_asset_policy import checked_asset_path
from backend.engine.world_location_fields import exit_fields, scene_fields
from backend.models.avatar import Avatar
from backend.models.world_entity import WorldEntity, WorldExit, WorldScene
from backend.utils.path_security import data_url_to_local_path

logger = logging.getLogger(__name__)


def normalize_exported_equipment(
    avatar: Avatar | None, entities: Sequence[WorldEntity]
) -> tuple[list[str], dict[str, str]]:
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


def serialize_world_location(obj: WorldScene | WorldExit | None) -> dict[str, Any] | None:
    if not obj:
        return None
    data = scene_fields(obj) if isinstance(obj, WorldScene) else {"id": obj.id, **exit_fields(obj)}
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


def _register_asset(path: str, template_id: str, asset_mapping: dict[str, str]) -> str:
    path = checked_asset_path(path, template_id)
    if path in asset_mapping:
        return asset_mapping[path]
    name = os.path.basename(path)
    destination = f"assets/{name}"
    if destination in asset_mapping.values():
        suffix = hashlib.sha256(path.encode()).hexdigest()[:16]
        destination = f"assets/{suffix}-{name}"
    asset_mapping[path] = destination
    return destination


def localize_archive_asset(
    path: str | None, adventure_dir: str, asset_mapping: dict[str, str], *, template_id: str
) -> str | None:
    if not path or not path.startswith("/data/"):
        return path
    local_full = data_url_to_local_path(path)
    if not local_full:
        raise ValueError("Archive image reference is invalid.")
    local_full = checked_asset_path(local_full, template_id)
    if os.path.exists(local_full):
        return _register_asset(local_full, template_id, asset_mapping)
    # Legacy stale links may resolve only within this adventure's own directory.
    name = os.path.basename(path)
    for root, _dirs, files in os.walk(adventure_dir):
        if name in files:
            return _register_asset(os.path.join(root, name), template_id, asset_mapping)
    return path


def _clean_avatar_item_references(avatar: Avatar) -> tuple[list[str], dict[str, str]]:
    def _normalize_item(item: Any) -> str | None:
        if isinstance(item, dict):
            value = item.get("id")
            return value if isinstance(value, str) else None
        return item if isinstance(item, str) else None

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
