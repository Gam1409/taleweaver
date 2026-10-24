"""Remove session-created topology absent from a restored registry."""

from sqlalchemy import delete, or_, select

from backend.engine.dynamic_locations.schema import registry
from backend.models.world_entity import WorldExit, WorldScene
from backend.models.world_map import WorldMap


async def prune(db, session_id: str, removed: set[str]) -> None:
    if not removed:
        return
    await db.execute(
        delete(WorldExit).where(
            WorldExit.session_id == session_id,
            or_(WorldExit.from_scene_id.in_(removed), WorldExit.to_scene_id.in_(removed)),
        )
    )
    await db.execute(
        delete(WorldScene).where(
            WorldScene.session_id == session_id,
            WorldScene.id.in_(removed),
        )
    )
    world = await db.scalar(select(WorldMap).where(WorldMap.session_id == session_id))
    if world:
        world.nodes = {k: v for k, v in (world.nodes or {}).items() if k not in removed}
        world.edges = [
            e
            for e in world.edges or []
            if e.get("from") not in removed and e.get("to") not in removed
        ]


async def rewind(db, state, previous: dict) -> None:
    removed = set(previous.get("places") or {}) - set(registry(state).get("places") or {})
    await prune(db, state.session_id, removed)
    world = await db.scalar(select(WorldMap).where(WorldMap.session_id == state.session_id))
    if world:
        world.current_scene_id = state.current_scene_id
