"""Owner-only access for private adventure operations, including every export format."""

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.adventure_template import AdventureTemplate


async def require_owned_template(
    db: AsyncSession, template_id: str, user_id: str
) -> AdventureTemplate:
    template = await db.scalar(
        select(AdventureTemplate).where(
            AdventureTemplate.id == template_id, AdventureTemplate.owner_id == user_id
        )
    )
    if template is None:
        raise HTTPException(404, "Adventure template not found.")
    return template
