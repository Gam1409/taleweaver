"""Session movement permissions, including places created during exploration."""

from typing import Any

from backend.engine.dynamic_locations.schema import KEY


def is_moveable(entity: Any, override: dict[str, Any]) -> bool:
    value = override.get("moveable")
    if value is not None:
        return bool(value)
    return (
        bool(getattr(entity, "moveable", False))
        or str(getattr(entity, "movement_type", "")).upper() == "MOVABLE"
    )


def allowed_scenes(entity: Any, overrides: dict[str, Any]) -> list[str]:
    override = overrides.get(entity.id, {})
    allowed = override.get("allowed_scenes")
    if allowed is None:
        allowed = getattr(entity, "allowed_scenes", None)
    if not allowed:
        return []  # An empty authored list means unrestricted movement.
    registry = overrides.get(KEY)
    dynamic = registry.get("places") if isinstance(registry, dict) else None
    dynamic = dynamic if isinstance(dynamic, dict) else {}
    return list(dict.fromkeys([*allowed, *dynamic]))
