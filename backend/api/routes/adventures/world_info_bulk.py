"""Preview and confirm a collection change without fetching its records to the client."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.routes.adventures.session_mutations import session_mutation_lease
from backend.api.routes.adventures.world_info_common import WorldInfoRoute
from backend.api.routes.adventures.world_info_entries import commit_changed
from backend.core.auth import get_current_user
from backend.core.database import get_db
from backend.engine.world_info import bulk, views
from backend.engine.world_info.bulk_contracts import BulkApply, BulkRequest
from backend.models.user import User

router = APIRouter(route_class=WorldInfoRoute)


@router.post("/entries/bulk/preview")
async def preview_collection(
    game_id: str,
    payload: BulkRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    return await bulk.preview(db, user.id, game_id, payload)


@router.post("/entries/bulk/apply", dependencies=[Depends(session_mutation_lease)])
async def apply_collection(
    game_id: str,
    payload: BulkApply,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    result = await bulk.apply(db, user.id, game_id, payload)
    await commit_changed(db, game_id, user)
    result["index"] = await views.index_state(db, user, game_id)
    return result
