"""Durable, coalescing memory maintenance: at most one model batch per idle slot."""

import asyncio
import logging
import time
from dataclasses import dataclass
from uuid import uuid4

from anyio import CancelScope
from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core import database
from backend.engine.memory_rag.cancellation import find_cancellation
from backend.engine.memory_rag.documents import MemoryDocument, collect_documents
from backend.engine.memory_rag.embeddings import MAX_TEXT_LENGTH, embed_texts
from backend.engine.memory_rag.scheduling import BackgroundDeferredError, scheduler
from backend.engine.memory_rag.settings import embedding_signature, read_settings
from backend.engine.memory_rag.sqlite_busy import is_sqlite_busy
from backend.engine.memory_rag.store import LanceMemoryStore, Scope
from backend.models.game_session import GameSession
from backend.models.memory_rag import MemoryIndexState
from backend.models.session_state import SessionState
from backend.models.user import User

logger = logging.getLogger(__name__)
BATCH_SIZE = 16
LEASE_SECONDS = 120.0
RETRY_SECONDS = 60.0
_tasks: dict[str, asyncio.Task] = {}
_wakeups: dict[str, str] = {}
_failures: dict[str, int] = {}


@dataclass(frozen=True)
class Claim:
    session_id: str
    user_id: str
    epoch: int
    revision: int
    token: str
    signature: str | None
    paused: bool


async def mark_dirty(
    db: AsyncSession, session_id: str, user_id: str, template_id: str | None
) -> None:
    """Join the caller's commit; a cache failure cannot undo canonical story data."""
    try:
        async with db.begin_nested():
            await _mark_dirty(db, session_id, user_id, template_id)
    except Exception as exc:
        if cancelled := find_cancellation(exc):
            raise cancelled from None
        if is_sqlite_busy(exc):
            from backend.engine.memory_rag.dirty_queue import queue_refresh

            queue_refresh(session_id, user_id)
            logger.debug("Memory queue write deferred while SQLite is busy for %s", session_id)
            return
        logger.exception("Could not queue memory maintenance for session %s", session_id)


async def _mark_dirty(
    db: AsyncSession, session_id: str, user_id: str, template_id: str | None
) -> None:
    result = await db.execute(
        update(MemoryIndexState)
        .where(MemoryIndexState.session_id == session_id, MemoryIndexState.user_id == user_id)
        .values(
            template_id=template_id,
            desired_revision=MemoryIndexState.desired_revision + 1,
        )
    )
    if result.rowcount:
        return
    db.add(MemoryIndexState(session_id=session_id, user_id=user_id, template_id=template_id))
    await db.flush()


async def request_update(session_id: str, user_id: str) -> None:
    """Queue only committed canonical data, including command/early-return turns."""
    # Finish this short, independently owned transaction before request cancellation.
    # No model or vector-store work runs inside this shield.
    with CancelScope(shield=True):
        try:
            async with database.AsyncSessionLocal() as db:
                session = await db.get(GameSession, session_id)
                if session is None or session.user_id != user_id:
                    return
                # This session owns only the queue transaction: failures must reach
                # the background retry loop after the session has been closed.
                await _mark_dirty(db, session_id, user_id, session.template_id)
                await db.commit()
            schedule(session_id, user_id)
        except Exception as exc:
            if cancelled := find_cancellation(exc):
                raise cancelled from None
            if is_sqlite_busy(exc):
                raise
            logger.exception("Could not schedule memory maintenance for session %s", session_id)


async def _claim(session_id: str, user_id: str) -> Claim | None:
    async with database.AsyncSessionLocal() as db:
        row = await db.get(MemoryIndexState, session_id)
        if row is None or row.user_id != user_id:
            return None
        token = str(uuid4())
        claimed = await db.execute(
            update(MemoryIndexState)
            .where(
                MemoryIndexState.session_id == session_id,
                MemoryIndexState.user_id == user_id,
                MemoryIndexState.epoch == row.epoch,
                or_(
                    MemoryIndexState.lease_until.is_(None),
                    MemoryIndexState.lease_until <= time.time(),
                ),
            )
            .values(lease_token=token, lease_until=time.time() + LEASE_SECONDS)
            .execution_options(synchronize_session=False)
        )
        if not claimed.rowcount:
            return None
        claim = Claim(
            session_id, user_id, row.epoch, row.desired_revision, token, row.signature, row.paused
        )
        await db.commit()
        return claim


def _fence(claim: Claim) -> tuple:
    return (
        MemoryIndexState.session_id == claim.session_id,
        MemoryIndexState.user_id == claim.user_id,
        MemoryIndexState.epoch == claim.epoch,
        MemoryIndexState.lease_token == claim.token,
        MemoryIndexState.lease_until > time.time(),
    )


async def _release(claim: Claim, **values: object) -> None:
    async with database.AsyncSessionLocal() as db:
        await db.execute(
            update(MemoryIndexState)
            .where(*_fence(claim))
            .values(lease_token=None, lease_until=None, **values)
        )
        await db.commit()


async def _load(claim: Claim) -> tuple[User | None, SessionState | None, list[MemoryDocument]]:
    async with database.AsyncSessionLocal() as db:
        user = await db.get(User, claim.user_id)
        state = await db.scalar(
            select(SessionState).where(SessionState.session_id == claim.session_id)
        )
        if user is None or state is None:
            return user, state, []
        documents = await collect_documents(db, state, claim.user_id)
        return user, state, documents


async def _summarize(claim: Claim, *, chronicle: bool) -> bool:
    from backend.engine.memory_rag.summaries import summarize_one_group

    if chronicle:
        from backend.engine.memory_rag.chronicle import compress_history_one_group

        summarize = compress_history_one_group
    else:
        summarize = summarize_one_group
    async with database.AsyncSessionLocal() as db:
        user = await db.get(User, claim.user_id)
        state = await db.scalar(
            select(SessionState).where(SessionState.session_id == claim.session_id)
        )
        if user is None or state is None:
            return False
        return await summarize(db, user, state, epoch=claim.epoch, lease_token=claim.token)


async def _write_batch(
    claim: Claim, signature: str, documents: list[MemoryDocument], vectors: list[list[float]]
) -> bool:
    scope = Scope(claim.user_id, claim.session_id, claim.epoch, signature)
    async with database.AsyncSessionLocal() as db:
        fenced = await db.execute(
            update(MemoryIndexState)
            .where(*_fence(claim), MemoryIndexState.paused.is_(False))
            .values(signature=signature, status="indexing", last_error=None)
        )
        if not fenced.rowcount:
            return False
        store = LanceMemoryStore()
        await store.upsert(scope, [document.to_dict() for document in documents], vectors)
        await store.prune_generations(scope)
        await db.commit()
        return True


async def _index_batch(claim: Claim, user: User, documents: list[MemoryDocument]) -> bool:
    settings = read_settings(user)
    existing = {}
    store = LanceMemoryStore()
    if claim.signature:
        scope = Scope(claim.user_id, claim.session_id, claim.epoch, claim.signature)
        existing = await store.list_document_hashes(scope)
    pending = [
        document for document in documents if existing.get(document.id) != document.source_hash
    ]
    batch = pending[:BATCH_SIZE]
    if not batch:
        return False
    if not scheduler.can_start_background():
        raise BackgroundDeferredError
    vectors = await embed_texts(
        user, [document.text[:MAX_TEXT_LENGTH] for document in batch], timeout=30
    )
    signature = embedding_signature(settings, len(vectors[0]))
    if claim.signature and claim.signature != signature:
        raise ValueError("Embedding dimensions changed. Rebuild the memory index.")
    return await _write_batch(claim, signature, batch, vectors)


async def _complete(claim: Claim, documents: list[MemoryDocument]) -> None:
    async with database.AsyncSessionLocal() as db:
        fenced = await db.execute(
            update(MemoryIndexState)
            .where(*_fence(claim), MemoryIndexState.paused.is_(False))
            .values(indexed_revision=claim.revision, status="ready", last_error=None)
        )
        if not fenced.rowcount:
            return
        if claim.signature:
            scope = Scope(claim.user_id, claim.session_id, claim.epoch, claim.signature)
            await LanceMemoryStore().prune(scope, [document.id for document in documents])
        await db.commit()


async def _step(claim: Claim) -> bool:
    user, state, documents = await _load(claim)
    if user is None or state is None:
        await _release(claim)
        return False
    enabled = read_settings(user).enabled and not claim.paused
    if enabled and await _index_batch(claim, user, documents):
        await _release(claim)
        return True
    if await _summarize(claim, chronicle=True):
        await _release(claim)
        return True
    if enabled and await _summarize(claim, chronicle=False):
        await _release(claim)
        return True
    if enabled:
        await _complete(claim, documents)
    await _release(claim)
    return False


async def _failed(claim: Claim) -> None:
    failures = _failures.get(claim.session_id, 0) + 1
    _failures[claim.session_id] = failures
    delay = min(RETRY_SECONDS * (2 ** min(failures - 1, 4)), 900)
    async with database.AsyncSessionLocal() as db:
        await db.execute(
            update(MemoryIndexState)
            .where(*_fence(claim))
            .values(
                lease_token=None,
                lease_until=time.time() + delay,
                status="paused" if claim.paused else "error",
                last_error="Memory maintenance failed. Check embedding and utility model settings, then retry.",
            )
        )
        await db.commit()


async def _process_claim(claim: Claim) -> bool:
    try:
        more = await _step(claim)
        _failures.pop(claim.session_id, None)
        return more
    except BackgroundDeferredError:
        await _release(claim)
        return True
    except asyncio.CancelledError:
        await _release(claim)
        raise
    except Exception:
        logger.exception("Memory maintenance failed for session %s", claim.session_id)
        await _failed(claim)
        return False


async def _idle_step(session_id: str, user_id: str) -> bool:
    async with scheduler.background():
        claim = await _claim(session_id, user_id)
        if claim is None:
            return False
        return await _process_claim(claim)


async def _run(session_id: str, user_id: str) -> None:
    while await _idle_step(session_id, user_id):
        pass


def schedule(session_id: str, user_id: str) -> None:
    if session_id in _tasks:
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
    if task.cancelled():
        return
    if task.exception():
        logger.error("Memory worker failed", exc_info=task.exception())
    if user_id:
        schedule(session_id, user_id)


async def shutdown() -> None:
    from backend.engine.memory_rag.dirty_queue import shutdown as stop_queue

    await stop_queue()
    _wakeups.clear()
    tasks = list(_tasks.values())
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    _failures.clear()
