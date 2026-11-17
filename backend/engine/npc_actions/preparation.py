"""Capture command working copies before inference; cognitive workers never query storage."""

from copy import deepcopy
from typing import Any

from backend.engine.clothing.context import actor_records
from backend.engine.clothing.visuals import detailed_for_state, session_objects
from backend.engine.npc_actions.preview import Draft, Scope
from backend.engine.physical_conditions.schema import KEY as CONDITIONS_KEY
from backend.engine.visual_novel.continuity import possession_snapshot


async def capture(manager: Any, views: dict, observed: Any) -> dict[str, Draft]:
    rows = await session_objects(manager.db, manager.game_id)
    actors = actor_records(manager, rows)
    possessions = possession_snapshot(manager, rows)
    conditions = (manager.state.entity_states or {}).get(CONDITIONS_KEY)
    states = {CONDITIONS_KEY: deepcopy(conditions)} if conditions is not None else {}
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
            )
        )
    return result
