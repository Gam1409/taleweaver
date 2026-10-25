"""Owner-scoped lookup and queued generation of completed VN moment illustrations."""

from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.routes.visual_jobs import VisualJobRequest, create_visual_job
from backend.core.auth import get_current_user
from backend.core.database import get_db
from backend.engine.scene_illustrations import SceneIllustrationRequest
from backend.engine.scene_illustrations.context import (
    illustration_status,
    owned_context,
    require_snapshot,
)
from backend.models.user import User

router = APIRouter(tags=["Scene illustrations"])


class QueueIllustrationRequest(SceneIllustrationRequest):
    job_id: UUID | None = None


@router.get("/{game_id}/illustrations")
async def read_illustration(
    game_id: str,
    message_id: str = Query(min_length=1, max_length=128),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    state, message = await owned_context(db, game_id, message_id, current_user.id)
    return illustration_status(state, message)


@router.post("/{game_id}/illustrations")
async def queue_illustration(
    game_id: str,
    payload: QueueIllustrationRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    state, message = await owned_context(db, game_id, payload.message_id, current_user.id)
    require_snapshot(state, message)
    await db.commit()
    return await create_visual_job(
        VisualJobRequest(
            id=payload.job_id or uuid4(),
            operation="session_illustration",
            session_id=game_id,
            payload={"message_id": payload.message_id},
        ),
        current_user,
    )
