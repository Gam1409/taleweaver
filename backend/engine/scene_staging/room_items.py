"""Canonical loose possessions remain in their room when their owner leaves."""

from types import SimpleNamespace
from typing import Any

from backend.engine.physical_conditions.scope import _visible_ids
from backend.engine.visual_novel.continuity import _inventory, _override

MAX_PROMPT_OBJECTS = 48


def candidates(rows: list[Any], state: Any) -> list[dict]:
    result = []
    states = state.entity_states or {}
    for row in rows:
        if row.entity_type != "OBJECT":
            continue
        override = states.get(row.id) or {}
        override = override if isinstance(override, dict) else {}
        metadata = getattr(row, "metadata_json", None)
        metadata = metadata if isinstance(metadata, dict) else {}
        runtime = override.get("vn_item_data")
        canonical = {
            **metadata,
            **(runtime if isinstance(runtime, dict) else {}),
        }
        owner = canonical.get("property_owner_id")
        if not isinstance(owner, str) or not owner:
            continue
        if (
            override.get("current_scene_id", getattr(row, "current_scene_id", None))
            != state.current_scene_id
        ):
            continue
        if override.get("is_in_inventory", getattr(row, "is_in_inventory", False)) or override.get(
            "is_hidden", getattr(row, "is_hidden", False)
        ):
            continue
        result.append(
            {
                "item_id": row.id,
                "owner_id": owner,
                "name": override.get("name", row.name),
                "spatial_position": override.get(
                    "spatial_position", getattr(row, "spatial_position", None)
                )
                or "",
                "scene_bound": True,
            }
        )
    return result


def placement_targets(avatar: Any, rows: list[Any], state: Any) -> dict[str, str | None]:
    """Keep unavailable IDs private while distinguishing them from unregistered scenery."""
    from backend.engine.scene_staging.props import _ids

    public = _visible_ids(SimpleNamespace(state=state), rows, None)
    held = _ids(getattr(avatar, "inventory", None))
    held.update(_ids((getattr(avatar, "equipment", None) or {}).values()))
    for row in rows:
        held.update(_ids(_inventory(row, _override(state, row.id))))
    public.difference_update(held)
    # An inline possession can have an ID without a corresponding world row.
    targets: dict[str, str | None] = dict.fromkeys(held)
    for row in rows:
        if row.entity_type != "OBJECT":
            continue
        name = _override(state, row.id).get("name", row.name)
        label = name.strip()[:120] if isinstance(name, str) else ""
        targets[row.id] = label if label and row.id in public else None
    return targets


def visible_targets(targets: dict[str, str | None], previous: dict) -> dict[str, str]:
    """Bound both request paths while keeping previously referenced objects in scope."""
    referenced = {
        placement["target"]
        for actor in previous.values()
        if (placement := actor.get("placement")) and placement["target_kind"] == "scene_object"
    }
    public = {key: name for key, name in targets.items() if name and len(key) <= 120}
    ordered = sorted(public, key=lambda key: (key not in referenced, key))
    return {key: public[key] for key in ordered[:MAX_PROMPT_OBJECTS]}
