"""Canonical review and explicit publication; gameplay writes share its lease."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.routes.adventures.session_mutations import session_mutation_lease
from backend.api.routes.adventures.world_info_common import WorldInfoRoute
from backend.core.auth import get_current_user
from backend.core.database import get_db
from backend.engine.memory_rag.control import invalidate
from backend.engine.memory_rag.settings import read_settings
from backend.engine.memory_rag.worker import schedule as schedule_index
from backend.engine.world_info import entries, limits, publishing, sources, views, worker
from backend.engine.world_info.access import WorldInfoError, owned_entry, owned_session
from backend.engine.world_info.schemas import (
    EntryFilters,
    EntrySort,
    EntryUpdate,
    EntryView,
    Publish,
    Version,
)
from backend.engine.world_info.types import EntryKind
from backend.models.memory_rag import MemoryIndexState
from backend.models.user import User

router = APIRouter(route_class=WorldInfoRoute)
write = [Depends(session_mutation_lease)]


async def _refresh_changed(db: AsyncSession, session_id: str, user: User) -> None:
    if not db.info.pop("world_info_changed", False) or not read_settings(user).enabled:
        return
    row = await db.get(MemoryIndexState, session_id, populate_existing=True)
    if row is not None and not row.paused:
        schedule_index(session_id, user.id)


def entry_filters(
    view: EntryView = "review",
    source_revision_id: str | None = Query(default=None, max_length=100),
    query: str = Query(default="", max_length=200),
    group_name: str | None = Query(default=None, max_length=limits.MAX_GROUP_CHARACTERS),
    tag: str | None = Query(default=None, min_length=1, max_length=limits.MAX_TAG_CHARACTERS),
    kind: EntryKind | None = None,
    sort: EntrySort = "newest",
) -> EntryFilters:
    return EntryFilters(
        view=view,
        source_revision_id=source_revision_id,
        query=query,
        group_name=group_name,
        tag=tag,
        kind=kind,
        sort=sort,
    )


@router.get("/entries")
async def list_entries(
    game_id: str,
    filters: EntryFilters = Depends(entry_filters),
    offset: int = Query(default=0, ge=0, le=limits.MAX_COUNTER),
    limit: int = Query(default=50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> object:
    return await views.list_entries(
        db,
        user.id,
        game_id,
        filters=filters,
        offset=offset,
        limit=limit,
    )


@router.get("/entries/facets")
async def entry_facets(
    game_id: str,
    filters: EntryFilters = Depends(entry_filters),
    facet_query: str = Query(default="", max_length=200),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> object:
    return await views.entry_facets(db, user.id, game_id, filters, facet_query=facet_query)


@router.get("/entries/{entry_id}")
async def entry_detail(
    game_id: str,
    entry_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> object:
    return await views.entry_detail(db, await owned_entry(db, user.id, game_id, entry_id))


@router.put("/entries/{entry_id}", dependencies=write)
async def update_entry(
    game_id: str,
    entry_id: str,
    payload: EntryUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> object:
    entry = await entries.update_entry(db, user.id, game_id, entry_id, payload)
    await db.commit()
    result = await views.entry_detail(db, entry)
    await _refresh_changed(db, game_id, user)
    return result


@router.delete("/entries/{entry_id}", dependencies=write)
async def delete_entry(
    game_id: str,
    entry_id: str,
    version: int = Query(ge=1, le=limits.MAX_COUNTER - 1),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    await entries.remove_entry(db, user.id, game_id, entry_id, version)
    await db.commit()
    await _refresh_changed(db, game_id, user)
    return {"deleted": True, "index": await views.index_state(db, user, game_id)}


@router.post("/entries/{entry_id}/unpublish", dependencies=write)
async def unpublish_entry(
    game_id: str,
    entry_id: str,
    payload: Version,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> object:
    entry = await entries.unpublish(db, user.id, game_id, entry_id, payload.version)
    await db.commit()
    result = await views.entry_detail(db, entry)
    await _refresh_changed(db, game_id, user)
    return result


@router.delete("/sources/{source_id}", dependencies=write)
async def delete_source(
    game_id: str,
    source_id: str,
    version: int = Query(ge=1, le=limits.MAX_COUNTER - 1),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    await sources.remove(db, user.id, game_id, source_id, version)
    await db.commit()
    worker.cancel_source(source_id)
    await _refresh_changed(db, game_id, user)
    return {"deleted": True, "index": await views.index_state(db, user, game_id)}


@router.post("/publish", dependencies=write)
async def publish_entries(
    game_id: str,
    payload: Publish,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    published, replaced, source = await publishing.publish(db, user.id, game_id, payload)
    await db.commit()
    result = {
        "published": published,
        "replaced": replaced,
        "source": await views.source_view(db, source),
        "index": await views.index_state(db, user, game_id),
    }
    await _refresh_changed(db, game_id, user)
    return result


@router.post("/index/rebuild", dependencies=write)
async def rebuild_index(
    game_id: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
) -> dict:
    session = await owned_session(db, user.id, game_id)
    if not read_settings(user).enabled:
        raise WorldInfoError(
            "Enable memory recall in administrator settings before rebuilding this session index.",
            409,
        )
    await db.execute(
        insert(MemoryIndexState)
        .values(
            session_id=game_id,
            user_id=user.id,
            template_id=session.template_id,
        )
        .on_conflict_do_nothing(index_elements=[MemoryIndexState.session_id])
    )
    row = await db.get(MemoryIndexState, game_id, populate_existing=True)
    if row is None:
        raise WorldInfoError("Session index is unavailable. Retry.", 409)
    await invalidate(db, row, paused=False)
    await db.commit()
    result = {"index": await views.index_state(db, user, game_id)}
    schedule_index(game_id, user.id)
    return result
