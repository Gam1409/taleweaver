"""Resume explicitly queued source batches in the shared idle scheduler."""

import asyncio
import logging
import time
from dataclasses import dataclass

from sqlalchemy import or_, select
from sqlalchemy.orm import defer

from backend.core import database
from backend.core.inference.registry import InferenceQueueError, InferenceUncertainError
from backend.core.llm_deadlines import role_timeout
from backend.engine.memory_rag import persistence, scheduling
from backend.engine.memory_rag.cancellation import find_cancellation
from backend.engine.memory_rag.persistence import retry_transaction
from backend.engine.memory_rag.sqlite_busy import is_sqlite_busy
from backend.engine.world_info import plan_cache, queue
from backend.engine.world_info.capacity import CapacityError
from backend.engine.world_info.extraction import MAX_REFERENCE_ENTRIES, extract_batch
from backend.engine.world_info.results import save_batch
from backend.engine.world_info.types import EntryReference, SourcePlan
from backend.models.game_session import GameSession
from backend.models.user import User
from backend.models.world_info import WorldInfoEntry, WorldInfoRevision, WorldInfoSource

logger = logging.getLogger(__name__)
_tasks: dict[str, asyncio.Task] = {}
_wakeups: dict[str, str] = {}
_timers: dict[str, asyncio.TimerHandle] = {}
_active: dict[str, tuple[str, asyncio.Task]] = {}
_stopping = asyncio.Event()


@dataclass(frozen=True)
class Prepared:
    user: User
    language: str
    plan: SourcePlan
    references: tuple[EntryReference, ...]


@retry_transaction
async def _prepare(claim: queue.Claim) -> Prepared | None:
    async with database.AsyncSessionLocal() as db:
        revision = await db.scalar(
            select(WorldInfoRevision)
            .where(*queue.fence(claim))
            .options(defer(WorldInfoRevision.content))
        )
        if revision is None:
            return None
        user = await db.get(User, claim.user_id)
        session = await db.get(GameSession, claim.session_id)
        if user is None or session is None or session.user_id != claim.user_id:
            return None
        if revision.processing_language is None:
            raise ValueError("Source processing language is not fixed.")
        plan = await plan_cache.load(db, revision)
        if claim.cursor >= len(plan.batches):
            raise ValueError("Processing cursor has no remaining batch.")
        rows = await db.execute(
            select(WorldInfoEntry.id, WorldInfoEntry.title, WorldInfoEntry.group_name)
            .join(WorldInfoRevision, WorldInfoRevision.id == WorldInfoEntry.source_revision_id)
            .join(WorldInfoSource, WorldInfoSource.id == WorldInfoEntry.source_id)
            .where(
                WorldInfoEntry.session_id == claim.session_id,
                WorldInfoEntry.user_id == claim.user_id,
                WorldInfoSource.session_id == claim.session_id,
                WorldInfoSource.user_id == claim.user_id,
                WorldInfoEntry.status.in_(["draft", "published"]),
                or_(
                    WorldInfoRevision.number == WorldInfoSource.current_revision,
                    WorldInfoRevision.number == WorldInfoSource.published_revision,
                ),
            )
            .order_by(
                (WorldInfoEntry.source_revision_id == claim.revision_id).desc(),
                WorldInfoEntry.batch_index.desc(),
                WorldInfoEntry.id,
            )
            .limit(MAX_REFERENCE_ENTRIES)
        )
        references = tuple(
            EntryReference(id=row.id, title=row.title, group_name=row.group_name) for row in rows
        )
        return Prepared(
            user,
            revision.processing_language,
            plan,
            references,
        )


def _error_code(error: Exception) -> str:
    if isinstance(error, queue.RequestBudgetError):
        return "request_limit"
    if isinstance(error, CapacityError):
        return "storage_limit"
    if isinstance(error, (InferenceQueueError, InferenceUncertainError)):
        return "inference_waiting"
    if isinstance(error, TimeoutError):
        return "timeout"
    if isinstance(error, ValueError):
        return "invalid_output"
    return "processing_failed"


async def process_claim(claim: queue.Claim) -> None:
    """Keep model work outside transactions; a save retry reuses the same output."""
    keep_plan = False
    try:
        prepared = await _prepare(claim)
        if prepared is None:
            return
        if not scheduling.scheduler.can_start_background():
            await queue.release(claim)
            return
        requests = 0

        async def before_request() -> None:
            nonlocal requests
            await queue.reserve_request(
                claim,
                ordinal=requests,
                lease_seconds=role_timeout(prepared.user, "generator") + queue.LEASE_GRACE_SECONDS,
            )
            requests += 1

        request = asyncio.create_task(
            extract_batch(
                prepared.user,
                claim.session_id,
                claim.revision_id,
                claim.content_hash,
                prepared.plan.batches[claim.cursor],
                prepared.references,
                language=prepared.language,
                before_request=before_request,
            )
        )
        _active[claim.revision_id] = claim.source_id, request
        try:
            entries = await request
        finally:
            _active.pop(claim.revision_id, None)
        saved = await save_batch(claim, entries)
        keep_plan = saved and claim.cursor + 1 < len(prepared.plan.batches)
    except queue.StaleJobError:
        return
    except asyncio.CancelledError as interrupted:
        await _release_interrupted(claim)
        task = asyncio.current_task()
        if task is not None and getattr(task, "cancelling", lambda: 0)():
            raise interrupted
    except Exception as error:
        if cancelled := find_cancellation(error):
            raise cancelled from None
        code = _error_code(error)
        await queue.release(claim, status="failed", error=code)
        logger.warning("World Info processing stopped (%s)", code)
    finally:
        if not keep_plan:
            plan_cache.discard_revision(claim.revision_id)


async def _release_interrupted(claim: queue.Claim) -> None:
    try:
        await queue.release(claim)
    except Exception:
        # A lost cleanup transaction leaves a reclaimable lease, not lost progress.
        logger.warning("World Info interrupted work will recover after its lease expires")


async def _next_retry(session_id: str, user_id: str) -> float | None:
    async with database.AsyncSessionLocal() as db:
        return await db.scalar(
            select(WorldInfoRevision.lease_until)
            .where(
                WorldInfoRevision.session_id == session_id,
                WorldInfoRevision.user_id == user_id,
                WorldInfoRevision.status == "processing",
                WorldInfoRevision.run_token.is_not(None),
                WorldInfoRevision.lease_until.is_not(None),
                queue.current_source(),
            )
            .order_by(WorldInfoRevision.lease_until)
            .limit(1)
        )


def _defer_busy(session_id: str, user_id: str, error: Exception) -> None:
    if not is_sqlite_busy(error):
        raise error
    if not _stopping.is_set():
        _timers[session_id] = asyncio.get_running_loop().call_later(
            persistence.RETRY_DELAYS[-1], schedule, session_id, user_id
        )
    logger.debug("World Info queue deferred while SQLite is busy")


async def _idle_step(session_id: str, user_id: str) -> bool | None:
    """Return True after a claim, False for no claim, or None for deferred acquisition."""
    async with scheduling.scheduler.background():
        try:
            claim = await queue.claim_next(session_id, user_id)
        except Exception as error:
            _defer_busy(session_id, user_id, error)
            return None
        if claim is not None:
            await process_claim(claim)
    return claim is not None


async def _run(session_id: str, user_id: str) -> None:
    while not _stopping.is_set():
        worked = await _idle_step(session_id, user_id)
        if worked is None:
            return
        if worked:
            continue
        try:
            when = await _next_retry(session_id, user_id)
        except Exception as error:
            _defer_busy(session_id, user_id, error)
            return
        if when is not None and not _stopping.is_set():
            _timers[session_id] = asyncio.get_running_loop().call_later(
                max(1, when - time.time()), schedule, session_id, user_id
            )
        if when is None:
            plan_cache.discard_session(session_id)
        return


def schedule(session_id: str, user_id: str) -> None:
    """Only callers with a committed explicit queue intent should wake this worker."""
    if _stopping.is_set():
        return
    timer = _timers.pop(session_id, None)
    if timer is not None:
        timer.cancel()
    if session_id in _tasks:
        # _finish consumes wakeups received during queue/lease awaits. Its
        # schedule call cancels any timer installed before this task exits.
        _wakeups[session_id] = user_id
        return
    task = asyncio.create_task(_run(session_id, user_id))
    _tasks[session_id] = task
    task.add_done_callback(lambda done: _finish(session_id, done))


def _finish(session_id: str, task: asyncio.Task) -> None:
    if _tasks.get(session_id) is not task:
        return
    _tasks.pop(session_id, None)
    user_id = _wakeups.pop(session_id, None)
    if not task.cancelled() and task.exception() is not None:
        logger.warning("World Info worker deferred after a processing error")
    if user_id and not _stopping.is_set():
        schedule(session_id, user_id)


def cancel_local(revision_id: str) -> None:
    """Call after durable token revocation; remote inference may still run."""
    plan_cache.discard_revision(revision_id)
    active = _active.get(revision_id)
    if active is not None:
        active[1].cancel()


def cancel_source(source_id: str) -> None:
    plan_cache.discard_source(source_id)
    for current_source, task in list(_active.values()):
        if source_id == current_source:
            task.cancel()


async def recover_pending() -> None:
    """Recover only work explicitly queued before restart, never uploaded/imported drafts."""
    async with database.AsyncSessionLocal() as db:
        rows = list(
            await db.execute(
                select(WorldInfoRevision.session_id, WorldInfoRevision.user_id)
                .where(
                    WorldInfoRevision.status.in_(["queued", "processing"]),
                    WorldInfoRevision.run_token.is_not(None),
                    queue.current_source(),
                )
                .distinct()
            )
        )
    for session_id, user_id in rows:
        schedule(session_id, user_id)


async def shutdown() -> None:
    _stopping.set()
    try:
        for timer in _timers.values():
            timer.cancel()
        _timers.clear()
        _wakeups.clear()
        tasks = list(_tasks.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    finally:
        _tasks.clear()
        _active.clear()
        plan_cache.clear()
        _stopping.clear()
