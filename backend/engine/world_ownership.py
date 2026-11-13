"""Keep running session worlds independent of their original template."""

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.world_entity import WorldEntity, WorldExit, WorldScene
from backend.models.world_map import WorldMap


async def detach_session_world(db: AsyncSession, template_id: str) -> None:
    """Repair legacy imports that associated session-owned rows with a template."""
    for model in (WorldScene, WorldExit, WorldEntity, WorldMap):
        await db.execute(
            update(model)
            .where(model.template_id == template_id, model.session_id.is_not(None))
            .values(template_id=None)
        )
