"""Durable per-narration work; background failures never roll back a player's turn."""

import asyncio
import logging
import time

from backend.core import database
from backend.core.diagnostic_operations import diagnostic_job
from backend.core.llm_deadlines import role_timeout
from backend.engine.memory_rag.persistence import retry_transaction
from backend.engine.memory_rag.scheduling import scheduler
from backend.engine.npc_journal import queue
from backend.engine.npc_journal.apply import apply_extraction
from backend.engine.npc_journal.extract import extract, extraction_context
from backend.engine.npc_journal.portraits import resume_pending, schedule_portrait
from backend.engine.npc_journal.schema import JournalExtraction
from backend.models.chat import ChatMessage
from backend.models.game_session import GameSession
from backend.models.user import User

logger = logging.getLogger(__name__)
_tasks: dict[str, asyncio.Task] = {}
_wakeups: dict[str, str] = {}
_cooldowns: dict[str, float] = {}


async def process_message(message_id: str, user_id: str) -> bool:
    """Claim once; retries re-read current NPC rows before applying facts."""
    task = None
    try:
        prepared = await _prepare(message_id, user_id)
        if prepared is None:
            return False
        user, session, task, original_content = prepared
        async with database.AsyncSessionLocal() as db:
            message = await db.get(ChatMessage, message_id)
            if message is None:
                return False
            payload, player_name = await extraction_context(db, message, session)
        result = await _extract_when_idle(user, session, message_id, payload, task)
        created = await _save(message_id, original_content, player_name, result, task["token"])
        if created is None:
            return False
        for npc_id in created:
            schedule_portrait(session.id, npc_id, user_id)
        return True
    except asyncio.CancelledError:
        if task:
            try:
                await _fail(message_id, task, interrupted=True)
            except Exception:
                logger.exception("Could not release interrupted journal task %s", message_id)
        raise
    except Exception:
        logger.exception("NPC journal extraction failed for message %s", message_id)
        if task:
            await _fail(message_id, task)
        return False


@retry_transaction
async def _prepare(message_id: str, user_id: str) -> tuple[User, GameSession, dict, str] | None:
    async with database.AsyncSessionLocal() as db:
        message = await db.get(ChatMessage, message_id)
        if message is None or message.role != "assistant":
            return None
        session = await db.get(GameSession, message.session_id)
        user = await db.get(User, user_id)
        if session is None or session.user_id != user_id or user is None:
            return None
        original_content = message.content
        task = await queue.claim(
            db, message, lease_seconds=role_timeout(user, "small") + queue.LEASE_SECONDS
        )
        if task is None:
            return None
        return user, session, task, original_content


async def _extract_when_idle(
    user: User, session: GameSession, message_id: str, payload: str, task: dict
) -> JournalExtraction | None:
    if not scheduler.can_start_background():
        await _defer(message_id, task)
        return None
    return await asyncio.wait_for(
        extract(user, session, message_id, payload), timeout=role_timeout(user, "small")
    )


@retry_transaction
async def _save(
    message_id: str,
    original_content: str,
    player_name: str,
    result: JournalExtraction | None,
    token: str,
) -> list[str] | None:
    if result is None:
        return None
    async with database.AsyncSessionLocal() as db:
        message = await db.get(ChatMessage, message_id)
        if message is None or message.content != original_content:
            return None
        if not await queue.fence(db, message, token):
            return None
        created = await apply_extraction(db, message, result, player_name)
        task = message.npc_journal or {}
        message.npc_journal = {
            "status": "done",
            "attempts": task["attempts"],
            "gaps": task.get("gaps", []),
        }
        if task.get("recovering"):
            await queue.requeue_dependents(db, message)
        from backend.engine.memory_rag.worker import mark_dirty
        from backend.engine.memory_rag.worker import schedule as schedule_memory

        session = await db.get(GameSession, message.session_id)
        if session is not None:
            await mark_dirty(db, session.id, session.user_id, session.template_id)
        await db.commit()
        if session is not None:
            schedule_memory(session.id, session.user_id)
        return created


@retry_transaction
async def _defer(message_id: str, task: dict) -> None:
    async with database.AsyncSessionLocal() as db:
        message = await db.get(ChatMessage, message_id)
        if message is None or not await queue.fence(db, message, task["token"]):
            return
        message.npc_journal = {
            **task,
            "status": "pending",
            "attempts": max(0, task["attempts"] - 1),
        }
        await db.commit()


@retry_transaction
async def _fail(message_id: str, task: dict, *, interrupted: bool = False) -> None:
    async with database.AsyncSessionLocal() as db:
        message = await db.get(ChatMessage, message_id)
        if message is None or not await queue.fence(db, message, task["token"]):
            return
        message.npc_journal = {
            "status": "failed",
            "attempts": task["attempts"],
            "gaps": task.get("gaps", []),
            "retry_after": time.time() + queue.RETRY_DELAY,
            "error": "Character learning was interrupted. Retry from Characters."
            if interrupted
            else "Could not update character knowledge. Check the Small / Utility model and retry.",
        }
        await db.commit()


@retry_transaction
async def _next_message(session_id: str) -> str | None:
    async with database.AsyncSessionLocal() as db:
        return await queue.next_message(db, session_id)


@diagnostic_job("npc_learning")
async def _run(session_id: str, user_id: str) -> None:
    if _cooldowns.get(session_id, 0) > time.monotonic():
        return
    _cooldowns.pop(session_id, None)
    await resume_pending(session_id, user_id)
    consecutive_failures = 0
    while True:
        async with scheduler.background():
            message_id = await _next_message(session_id)
            if message_id is None:
                return
            success = await process_message(message_id, user_id)
            consecutive_failures = 0 if success else consecutive_failures + 1
            if consecutive_failures >= 2:
                # A failing provider must not consume the backlog on every UI poll.
                _cooldowns[session_id] = time.monotonic() + queue.RETRY_DELAY
                return


def schedule(session_id: str, user_id: str, *, retry: bool = False) -> None:
    if retry:
        _cooldowns.pop(session_id, None)
    if _cooldowns.get(session_id, 0) > time.monotonic():
        return
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
        logger.error("NPC journal task failed", exc_info=task.exception())
    if user_id:
        schedule(session_id, user_id)


async def shutdown() -> None:
    from backend.engine.npc_journal.portraits import shutdown as stop_portraits

    _wakeups.clear()
    tasks = list(_tasks.values())
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    _cooldowns.clear()
    await stop_portraits()
