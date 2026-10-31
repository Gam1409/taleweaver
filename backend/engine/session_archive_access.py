"""Resolve optional template links without granting access through uploaded saves."""

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.adventure_template import AdventureTemplate


async def accessible_template(
    db: AsyncSession, template_id: str | None, owner_id: str
) -> str | None:
    if not template_id:
        return None
    resolved = await db.scalar(
        select(AdventureTemplate.id).where(
            AdventureTemplate.id == template_id,
            or_(AdventureTemplate.owner_id == owner_id, AdventureTemplate.is_ready.is_(True)),
        )
    )
    return str(resolved) if resolved is not None else None
