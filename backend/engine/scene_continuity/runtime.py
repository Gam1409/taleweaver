"""Share extraction and atomically bind deltas to the saved assistant message."""

from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select

from backend.core.engine_detailed_trace import step, sync_step
from backend.models.world_entity import WorldScene

from .ledger import apply
from .presentation import project
from .schema import KEY


@dataclass
class Pending:
    before: Any
    scene_id: str
    scene_description: str
    targets: set[str]
    actor_targets: set[str]
    updates: list[Any] | None = None
    actions: list[Any] | None = None


@step("scene.prepare")
async def prepare(manager: Any) -> dict:
    from backend.engine.gameplay.world import AdventureLogic

    manager._pending_scene_continuity = None
    scene_id = manager.state.current_scene_id
    scene = await manager.db.scalar(
        select(WorldScene).where(
            WorldScene.session_id == manager.state.session_id,
            WorldScene.id == scene_id,
        )
    )
    entities = await AdventureLogic.build_session_entities(manager.db, manager.state)
    targets = {"__player__", scene_id, *(str(row["id"]) for row in entities)}
    description = str(getattr(scene, "description", "") or "")
    manager._pending_scene_continuity = Pending(
        deepcopy((manager.state.entity_states or {}).get(KEY)),
        scene_id,
        description,
        targets,
        {"__player__", *(str(row["id"]) for row in entities if row.get("entity_type") == "NPC")},
    )
    return {
        "scene_id": scene_id,
        "scene_description": description,
        "public_subjects": [
            {key: row.get(key) for key in ("id", "name", "entity_type", "description", "notes")}
            for row in entities
        ],
        "saved": project(
            manager.state,
            actor_id="__player__",
            targets=targets,
            scene_description=description,
            include_private=True,
        ),
    }


def complete(manager: Any, updates: list[Any], actions: list[Any]) -> None:
    pending = getattr(manager, "_pending_scene_continuity", None)
    if isinstance(pending, Pending):
        pending.updates, pending.actions = deepcopy(updates), deepcopy(actions)


@sync_step("scene.commit")
def finish(manager: Any, message: Any) -> list[str]:
    pending = getattr(manager, "_pending_scene_continuity", None)
    manager._pending_scene_continuity = None
    if not isinstance(pending, Pending) or pending.updates is None:
        return []
    states = manager.state.entity_states or {}
    if states.get(KEY) != pending.before or pending.scene_id != manager.state.current_scene_id:
        return ["Scene continuity needs review: the source state changed during extraction."]
    try:
        result, errors = apply(
            states,
            pending.updates,
            pending.actions or [],
            message=message,
            scene_id=pending.scene_id,
            scene_description=pending.scene_description,
            session_id=manager.state.session_id,
            minute=int(manager.state.in_game_time or 0),
            targets=pending.targets,
            actor_targets=pending.actor_targets,
        )
    except ValueError:
        return ["Scene continuity is invalid and was preserved; review Debug → State."]
    manager.state.entity_states = result
    return (
        ["Some scene continuity updates need review; previous facts were preserved."]
        if errors
        else []
    )
