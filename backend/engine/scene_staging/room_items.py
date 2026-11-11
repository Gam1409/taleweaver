"""Canonical loose possessions remain in their room when their owner leaves."""

from typing import Any


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
