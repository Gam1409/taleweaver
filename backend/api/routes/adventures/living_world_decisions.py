"""Explicit private decisions with short leases before and after remote inference."""

import logging

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.auth import get_current_user
from backend.core.database import get_db
from backend.engine.living_world import orchestration
from backend.engine.living_world.schema import Command
from backend.models.user import User

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Living World"])


@router.post("/{game_id}/living-world/deliberate")
async def deliberate(
    game_id: str,
    payload: Command,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    return await orchestration.deliberate(game_id, payload, db=db, user=user)


@router.post("/{game_id}/living-world/cycle")
async def cycle(
    game_id: str,
    payload: Command,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    return await orchestration.cycle(game_id, payload, db=db, user=user)
