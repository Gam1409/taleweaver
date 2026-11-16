"""Protect selected checkpoints from automatic retention pruning."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, StrictBool
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.routes.adventures.session_mutations import session_mutation_lease
from backend.core.auth import get_current_user
from backend.core.database import get_db
from backend.models.game_session import GameSession
from backend.models.session_checkpoint import SessionCheckpoint
from backend.models.user import User

router = APIRouter(dependencies=[Depends(session_mutation_lease)])


class PinRequest(BaseModel):
    pinned: StrictBool


@router.patch("/sessions/{game_id}/checkpoints/{checkpoint_id}/pin")
async def pin_checkpoint(
    game_id: str,
    checkpoint_id: str,
    payload: PinRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    owner = await db.scalar(
        select(GameSession.id).where(GameSession.id == game_id, GameSession.user_id == user.id)
    )
    checkpoint = await db.get(SessionCheckpoint, checkpoint_id) if owner else None
    if checkpoint is None or checkpoint.session_id != game_id:
        raise HTTPException(404, "Checkpoint not found.")
    checkpoint.state_snapshot = {**(checkpoint.state_snapshot or {}), "pinned": payload.pinned}
    await db.commit()
    return {"pinned": payload.pinned}
