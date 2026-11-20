"""Read public routes through the movement owner without disclosing locks or scripts."""

from typing import Any

from backend.engine.narrated_movement.context import context as movement_context
from backend.engine.scene_continuity.scope import SceneScope


async def capture(manager: Any, rows: list[Any]) -> dict:
    """Use the same directional routes, effective lock state and mobility constraints."""
    return await movement_context(manager, rows)


def project(manager: Any, context: dict, observer_id: str) -> dict:
    actor = context.get("actors", {}).get(observer_id)
    if actor is None or context.get("scene_id") != manager.state.current_scene_id:
        return {"routes_knowledge": "unavailable"}
    permitted = set(actor["allowed_destinations"])
    scope = getattr(manager, "_scene_continuity_scope", None)
    description = (
        scope.description
        if isinstance(scope, SceneScope) and scope.scene_id == context["scene_id"]
        else None
    )
    return {
        "routes_knowledge": "visible_routes_only",
        "can_move": actor["can_move"],
        "routes": [
            {**route, "permitted": not route["locked"] and route["scene_id"] in permitted}
            for route in context["routes"]
        ],
        "description": description[:600] if description is not None else None,
        "description_truncated": bool(description is not None and len(description) > 600),
    }
