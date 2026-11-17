"""Capture command working copies before inference; cognitive workers never query storage."""

from copy import deepcopy
from typing import Any

from backend.engine import turn_controls
from backend.engine.clothing.context import actor_records
from backend.engine.clothing.visuals import detailed_for_state, session_objects
from backend.engine.npc_actions.preview import Draft, Scope
from backend.engine.physical_conditions.schema import KEY as CONDITIONS_KEY
from backend.engine.scene_staging.shared import _cast
from backend.engine.scene_staging.state import KEY as STAGING_KEY
from backend.engine.visual_novel.config import read_settings
from backend.engine.visual_novel.continuity import possession_snapshot


async def capture(manager: Any, views: dict, observed: Any) -> dict[str, Draft]:
    rows = await session_objects(manager.db, manager.game_id)
    actors = actor_records(manager, rows)
    possessions = possession_snapshot(manager, rows)
    states = {
        key: deepcopy(manager.state.entity_states[key])
        for key in (CONDITIONS_KEY, STAGING_KEY)
        if key in (manager.state.entity_states or {})
    }
    cast = tuple(_cast(manager, actors, rows))
    result = {}
    for actor_id, view in views.items():
        if (
            view.session_id != manager.game_id
            or view.message_id != observed.message_id
            or view.scene_id != manager.state.current_scene_id
        ):
            raise ValueError("The command view belongs to another session, input or scene.")
        destinations = frozenset(
            route["scene_id"] for route in view.scene.get("routes", []) if route.get("permitted")
        )
        result[actor_id] = Draft(
            Scope(
                manager.game_id,
                observed.message_id,
                actor_id,
                view.scene_id,
                deepcopy(actors),
                deepcopy(possessions),
                deepcopy(states),
                frozenset(view.entities),
                destinations,
                detailed_for_state(manager.state),
                int(manager.state.in_game_time or 0),
                input_hash=observed.content_hash,
                input_revision=observed.revision_id,
                player_id=manager.avatar.id,
                cast=cast,
                scene_objects={
                    key: row["name"][:120]
                    for key, row in view.entities.items()
                    if row["kind"] == "item" and row.get("owner_id") == "__scene__"
                },
                staging_enabled=read_settings(manager.state).scene_staging,
                observation=observed.model_copy(deep=True),
                control=turn_controls.scope(manager, "npc_command_preview", observation=observed),
            )
        )
    return result
