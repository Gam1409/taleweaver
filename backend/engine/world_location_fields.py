"""Portable scene and exit fields, independent of template/session ownership."""

from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from backend.models.world_entity import WorldExit, WorldScene

SCENE_HOOK_FIELDS = (
    "on_enter_scene_script",
    "on_enter_scene_text",
    "on_leave_scene_script",
    "on_leave_scene_text",
)
EXIT_RULE_FIELDS = (
    "unlock_expression",
    "on_open_exit_script",
    "on_open_exit_text",
    "on_exit_used_script",
    "on_exit_used_text",
    "on_unlock_success_script",
    "on_unlock_success_text",
    "on_unlock_failure_script",
    "on_unlock_failure_text",
)
SCENE_FIELDS = (
    "id",
    "label",
    "description",
    "image_url",
    "decorative_objects",
    *SCENE_HOOK_FIELDS,
)
EXIT_FIELDS = (
    "from_scene_id",
    "to_scene_id",
    "label",
    "exit_type",
    "is_locked",
    "lock_description",
    "code_to_unlock",
    "item_to_unlock",
    "rule_to_unlock",
    *EXIT_RULE_FIELDS,
)


def scene_fields(source: WorldScene | Mapping[str, Any]) -> dict[str, Any]:
    """Copy portable values; ownership and generated asset URLs belong to the caller."""
    return _copy_fields(source, SCENE_FIELDS, {})


def exit_fields(source: WorldExit | Mapping[str, Any]) -> dict[str, Any]:
    """Copy exit rules while retaining legacy defaults for absent archive fields."""
    return _copy_fields(source, EXIT_FIELDS, {"exit_type": "one_way", "is_locked": False})


def _copy_fields(
    source: WorldScene | WorldExit | Mapping[str, Any],
    fields: tuple[str, ...],
    defaults: dict[str, Any],
) -> dict[str, Any]:
    if isinstance(source, Mapping):
        return {key: deepcopy(source.get(key, defaults.get(key))) for key in fields}
    return {key: deepcopy(getattr(source, key)) for key in fields}
