"""Share the current scene projection between normal and simplified NPC narration."""

from typing import Any

from backend.core.engine_detailed_trace import step
from backend.engine.chpm import context, host_observations, recent_scene
from backend.engine.chpm.host_observation_contracts import HostFacts
from backend.engine.scene_continuity.scope import SceneScope
from backend.engine.scene_staging import props


@step("npc.scene_context")
async def prepare(manager: Any, turn: Any, actors: list[Any]) -> dict:
    names = {actor.id for actor in actors}
    scope = getattr(manager, "_scene_continuity_scope", None)
    targets = set(scope.targets) if isinstance(scope, SceneScope) else {"__player__", *names}
    views = await recent_scene.capture(manager, names, targets)
    manager._chpm_scene_observations = recent_scene.Cache(
        turn.input_id, manager.state.current_scene_id, views
    )
    turn.scene_cues = {
        actor: "\n".join(action.quote for action in view.actions) for actor, view in views.items()
    }
    return views


def capture(manager: Any, actor: Any, names: dict[str, str]) -> HostFacts:
    scope = getattr(manager, "_scene_continuity_scope", None)
    observed = recent_scene.available(manager, actor.id)
    if not isinstance(scope, SceneScope) or scope.scene_id != manager.state.current_scene_id:
        return host_observations.capture(manager.state, actor, names, last_observed_scene=observed)
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
        last_observed_scene=observed,
    )


def _person(actor: Any, state: Any) -> dict:
    override = (state.entity_states or {}).get(actor.id) or {}
    return {
        "id": actor.id,
        "position": override.get("spatial_position", getattr(actor, "spatial_position", None)),
    }
