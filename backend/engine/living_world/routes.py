"""Session-owned oriented passages retain the stored row for background permission checks."""

from typing import Any

from sqlalchemy import case, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.engine.exit_adjacency import outgoing_condition
from backend.models.session_state import SessionState
from backend.models.world_entity import WorldExit, WorldScene


async def outgoing(
    db: AsyncSession, state: SessionState, origin: str
) -> list[tuple[WorldExit, WorldScene]]:
    target_id = case(
        (WorldExit.from_scene_id == origin, WorldExit.to_scene_id), else_=WorldExit.from_scene_id
    )
    rows = await db.execute(
        select(WorldExit, WorldScene)
        .join(
            WorldScene,
            (WorldScene.id == target_id) & (WorldScene.session_id == WorldExit.session_id),
        )
        .where(WorldExit.session_id == state.session_id, outgoing_condition(origin))
        .order_by(WorldExit.id)
    )
    return [(edge, target) for edge, target in rows]


def lock_state(state: SessionState, edge: WorldExit, origin: str, target: str) -> dict[str, Any]:
    overrides = state.exit_states or {}
    return {
        **overrides.get(edge.id, {}),
        **overrides.get(f"{edge.from_scene_id}:{edge.to_scene_id}", {}),
        **overrides.get(f"{origin}:{target}", {}),
    }


def permitted(
    state: SessionState,
    edge: WorldExit,
    target: WorldScene,
    allowed: list,
    *,
    origin: str | None = None,
) -> bool:
    lock = lock_state(state, edge, origin or edge.from_scene_id, target.id)
    return not (
        lock.get("is_locked", edge.is_locked)
        or (allowed and target.id not in allowed)
        or edge.on_exit_used_script
        or edge.on_open_exit_script
        or target.on_enter_scene_script
        or edge.rule_to_unlock
        or edge.unlock_expression
    )
