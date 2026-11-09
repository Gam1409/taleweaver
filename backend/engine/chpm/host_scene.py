"""Share the current scene projection between normal and simplified NPC narration."""

from typing import Any

from backend.engine.chpm import context, host_observations
from backend.engine.chpm.host_observation_contracts import HostFacts
from backend.engine.scene_continuity.scope import SceneScope
from backend.engine.scene_staging import props


def capture(manager: Any, actor: Any, names: dict[str, str]) -> HostFacts:
    scope = getattr(manager, "_scene_continuity_scope", None)
    if not isinstance(scope, SceneScope) or scope.scene_id != manager.state.current_scene_id:
        return host_observations.capture(manager.state, actor, names)
    present = {
        row.id: row
        for row in scope.entities
        if row.id in scope.targets and context.available(row, manager.state)
    }
    cast = [_person(manager.avatar, manager.state)]
    cast.extend(_person(row, manager.state) for row in present.values())
    items = props.candidates(manager.avatar, list(scope.entities), manager.state, set(present))
    return host_observations.capture(
        manager.state,
        actor,
        {key: str(row.name) for key, row in present.items()},
        scene_targets=set(scope.targets),
        scene_description=scope.description,
        staging_cast=cast,
        placed_items=items,
        player_id=manager.avatar.id,
    )


def _person(actor: Any, state: Any) -> dict:
    override = (state.entity_states or {}).get(actor.id) or {}
    return {
        "id": actor.id,
        "position": override.get("spatial_position", getattr(actor, "spatial_position", None)),
    }
