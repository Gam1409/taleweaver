"""Rewrite authored ID references without modifying prose or executable source."""

from copy import deepcopy
from typing import Any, Literal

from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.routes.adventures.editing.common import _get_template_avatar
from backend.api.routes.adventures.editing.entity_update.fields import template_rows
from backend.models.adventure_template import AdventureTemplate
from backend.models.world_entity import WorldEntity

ReferenceKind = Literal["entity", "scene"]
_SCALARS = {
    "entity": {
        "required_item_id",
        "required_defeated_npc_id",
        "unlock_required_item_id",
        "unlock_required_defeated_npc_id",
        "unlock_condition_target",
        "item_to_unlock",
        "equipped_weapon_id",
        "equipped_armor_id",
        "reveals_item_id",
    },
    "scene": {
        "required_scene_id",
        "unlock_required_scene_id",
        "current_scene_id",
        "from_scene_id",
        "to_scene_id",
        "start_scene_id",
    },
}
_DEFINITIONS = {"entity": {"objects", "npcs", "entities"}, "scene": {"scenes"}}
_INVENTORIES = {"inventory", "starting_inventory"}
_EQUIPMENT = {"equipment", "starting_equipment"}
_SCRIPT_TARGET_KIND = {"on_enter_scene": "scene", "on_interact": "entity"}


def _reference(value: Any, old_id: str, new_id: str) -> Any:
    if value == old_id:
        return new_id
    if isinstance(value, dict) and value.get("id") == old_id:
        return {**value, "id": new_id}
    return value


def _rewrite_targets(data: dict[str, Any], old_id: str, new_id: str, kind: ReferenceKind) -> None:
    trigger = data.get("trigger")
    if isinstance(trigger, str) and _SCRIPT_TARGET_KIND.get(trigger) == kind:
        data.update(
            {field: new_id for field in ("target_id", "target") if data.get(field) == old_id}
        )
    if (
        kind == "entity"
        and data.get("type") == "unlock_container"
        and data.get("target_id") == old_id
    ):
        data["target_id"] = new_id
    if kind == "scene" and data.get("type") == "unlock_exit":
        target = data.get("target_id")
        if isinstance(target, str) and target.count(":") == 1:
            data["target_id"] = ":".join(
                new_id if part == old_id else part for part in target.strip().split(":")
            )


def renamed_references(
    value: Any, old_id: str, new_id: str, kind: ReferenceKind, *, field: str = ""
) -> Any:
    """Copy known structured reference fields; IDs of quests/scripts and text stay intact."""
    if isinstance(value, list):
        renamed = [renamed_references(item, old_id, new_id, kind, field=field) for item in value]
        if field in _DEFINITIONS[kind] or (kind == "entity" and field in _INVENTORIES):
            return [_reference(item, old_id, new_id) for item in renamed]
        if field == ("allowed_scenes" if kind == "scene" else "combination_ingredients"):
            return [new_id if item == old_id else item for item in renamed]
        return renamed
    if not isinstance(value, dict):
        return deepcopy(value)
    result = {
        key: renamed_references(item, old_id, new_id, kind, field=key)
        for key, item in value.items()
    }
    for key in _SCALARS[kind]:
        if result.get(key) == old_id:
            result[key] = new_id
    if kind == "entity" and field in _EQUIPMENT:
        result = {slot: _reference(item, old_id, new_id) for slot, item in result.items()}
    if kind == "entity" and field == "gates" and result.get("item") == old_id:
        result["item"] = new_id
    _rewrite_targets(result, old_id, new_id, kind)
    return result


def _update_json(target: Any, field: str, old_id: str, new_id: str, kind: ReferenceKind) -> None:
    before = getattr(target, field)
    after = renamed_references(before, old_id, new_id, kind, field=field)
    if after != before:
        setattr(target, field, after)


async def cascade_template_references(
    db: AsyncSession, adventure: AdventureTemplate, old_id: str, new_id: str, kind: ReferenceKind
) -> None:
    """Keep every write within the caller's existing rename transaction and template scope."""
    for field in ("quests", "sequences", "awards", "original_manifest"):
        _update_json(adventure, field, old_id, new_id, kind)
    for entity in await template_rows(db, WorldEntity, adventure.id):
        _update_json(entity, "metadata_json", old_id, new_id, kind)
        if kind == "scene":
            _update_json(entity, "allowed_scenes", old_id, new_id, kind)
    avatar = await _get_template_avatar(db, adventure.id)
    if avatar is not None:
        _update_json(avatar, "stats", old_id, new_id, kind)
