"""Select a real starting location after a generated world replaces its placeholder."""

from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.routes.adventures.logic import AdventureLogic
from backend.models.session_state import SessionState
from backend.models.world_entity import WorldScene
from backend.models.world_map import WorldMap


async def ensure_generated_session_scene(
    db: AsyncSession, template_id: str, state: SessionState
) -> None:
    """Repair only invalid placeholder locations; preserve sessions already in a real scene."""
    result = await db.execute(
        select(WorldScene.id).where(WorldScene.session_id == state.session_id)
    )
    scene_ids = set(result.scalars().all())
    if not scene_ids or state.current_scene_id in scene_ids:
        return
    initial = await AdventureLogic.resolve_initial_scene_id(db, template_id)
    if initial not in scene_ids:
        initial = sorted(scene_ids)[0]
    existing: Any = state.discovered_scenes
    discovered = (
        [value for value in existing if value in scene_ids] if isinstance(existing, list) else []
    )
    if initial not in discovered:
        discovered.append(initial)
    await db.execute(
        update(SessionState)
        .where(SessionState.id == state.id)
        .values(current_scene_id=initial, discovered_scenes=discovered)
    )
    await db.execute(
        update(WorldMap)
        .where(WorldMap.session_id == state.session_id)
        .values(current_scene_id=initial)
    )
