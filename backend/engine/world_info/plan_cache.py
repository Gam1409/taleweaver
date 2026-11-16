"""Small process-local parsing cache; immutable SQL revisions remain authoritative."""

from collections import OrderedDict
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.engine.world_info import jobs
from backend.engine.world_info.types import SourcePlan
from backend.models.world_info import WorldInfoRevision

MAX_CACHED_SESSIONS = 4


@dataclass(frozen=True)
class CachedPlan:
    key: tuple
    source_id: str
    revision_id: str
    plan: SourcePlan


_plans: OrderedDict[str, CachedPlan] = OrderedDict()


def _key(revision: WorldInfoRevision) -> tuple:
    return (
        revision.user_id,
        revision.id,
        revision.source_id,
        revision.content_hash,
        revision.format,
        revision.parser_version,
        revision.extraction_version,
    )


async def load(db: AsyncSession, revision: WorldInfoRevision) -> SourcePlan:
    """The caller has already checked the current source and its worker claim."""
    key = _key(revision)
    cached = _plans.get(revision.session_id)
    if cached is not None and cached.key == key:
        _plans.move_to_end(revision.session_id)
        return jobs.validate_progress(revision, cached.plan)
    content = await db.scalar(
        select(WorldInfoRevision.content).where(
            WorldInfoRevision.id == revision.id,
            WorldInfoRevision.user_id == revision.user_id,
            WorldInfoRevision.session_id == revision.session_id,
            WorldInfoRevision.content_hash == revision.content_hash,
        )
    )
    if content is None:
        raise jobs.JobConflictError("Source revision changed before processing.")
    plan = jobs.parse_plan(revision, content)
    _plans[revision.session_id] = CachedPlan(key, revision.source_id, revision.id, plan)
    _plans.move_to_end(revision.session_id)
    while len(_plans) > MAX_CACHED_SESSIONS:
        _plans.popitem(last=False)
    return plan


def discard_revision(revision_id: str) -> None:
    for session_id, cached in list(_plans.items()):
        if cached.revision_id == revision_id:
            _plans.pop(session_id, None)


def discard_session(session_id: str) -> None:
    _plans.pop(session_id, None)


def discard_source(source_id: str) -> None:
    for session_id, cached in list(_plans.items()):
        if cached.source_id == source_id:
            _plans.pop(session_id, None)


def clear() -> None:
    _plans.clear()
