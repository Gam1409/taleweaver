"""Session-only knowledge sources, processing controls and canonical read views."""

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.routes.adventures.world_info_bulk import router as bulk_router
from backend.api.routes.adventures.world_info_common import WorldInfoRoute
from backend.api.routes.adventures.world_info_entries import router as entries_router
from backend.api.routes.adventures.world_info_upload import read_upload
from backend.core.auth import get_current_user
from backend.core.database import get_db
from backend.engine.world_info import jobs, limits, sources, views, worker
from backend.engine.world_info.access import owned_revision, owned_session, owned_source
from backend.engine.world_info.schemas import ControlVersion
from backend.models.user import User

router = APIRouter(prefix="/{game_id}/world-info", tags=["World Info"], route_class=WorldInfoRoute)
router.include_router(entries_router)
router.include_router(bulk_router)


@router.get("")
async def overview(
    game_id: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
) -> object:
    return await views.overview(db, user, game_id)


@router.post("/sources", status_code=201)
async def upload_source(
    game_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    await owned_session(db, user.id, game_id)
    payload = await read_upload(request)
    source, revision, duplicate = await sources.upload(db, user.id, game_id, **payload)
    await db.commit()
    return {
        "source": await views.source_view(db, source),
        "revision": await views.revision_view(db, revision),
        "duplicate": duplicate,
    }


@router.post("/sources/{source_id}/revisions", status_code=201)
async def replace_source(
    game_id: str,
    source_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    await owned_source(db, user.id, game_id, source_id)
    payload = await read_upload(request, replacing=True)
    source, revision, duplicate = await sources.replace(db, user.id, game_id, source_id, **payload)
    await db.commit()
    if not duplicate:
        worker.cancel_source(source_id)
    return {
        "source": await views.source_view(db, source),
        "revision": await views.revision_view(db, revision),
        "duplicate": duplicate,
    }


@router.get("/sources/{source_id}")
async def source_detail(
    game_id: str,
    source_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> object:
    return await views.source_detail(db, await owned_source(db, user.id, game_id, source_id))


@router.get("/revisions/{revision_id}")
async def revision_detail(
    game_id: str,
    revision_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> object:
    return await views.revision_detail(db, await owned_revision(db, user.id, game_id, revision_id))


@router.get("/revisions/{revision_id}/content")
async def revision_content(
    game_id: str,
    revision_id: str,
    offset: int = Query(default=0, ge=0, le=limits.MAX_SOURCE_CHARACTERS),
    limit: int = Query(
        default=limits.MAX_PREVIEW_CHARACTERS, ge=1, le=limits.MAX_PREVIEW_CHARACTERS
    ),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> object:
    return await views.revision_content(
        db,
        await owned_revision(db, user.id, game_id, revision_id),
        offset=offset,
        limit=limit,
    )


@router.post("/revisions/{revision_id}/process")
async def process_revision(
    game_id: str,
    revision_id: str,
    payload: ControlVersion,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> object:
    revision = await jobs.start_processing(
        db, user.id, game_id, revision_id, payload.control_version
    )
    await db.commit()
    worker.schedule(game_id, user.id)
    return await views.revision_detail(db, revision)


@router.post("/revisions/{revision_id}/cancel")
async def cancel_revision(
    game_id: str,
    revision_id: str,
    payload: ControlVersion,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> object:
    revision = await jobs.cancel_processing(
        db, user.id, game_id, revision_id, payload.control_version
    )
    await db.commit()
    worker.cancel_local(revision_id)
    return await views.revision_detail(db, revision)
