"""Durable per-narration work; background failures never roll back a player's turn."""

import asyncio
import logging
import time

from backend.core import database
from backend.engine.npc_journal import queue
from backend.engine.npc_journal.apply import apply_extraction
from backend.engine.npc_journal.extract import extract, extraction_context
from backend.engine.npc_journal.portraits import resume_pending, schedule_portrait
from backend.engine.npc_journal.schema import JournalExtraction
from backend.models.chat import ChatMessage
from backend.models.game_session import GameSession
from backend.models.user import User

logger = logging.getLogger(__name__)
EXTRACTION_TIMEOUT = 90
_tasks: dict[str, asyncio.Task] = {}
_wakeups: dict[str, str] = {}
_cooldowns: dict[str, float] = {}
_capacity = asyncio.Semaphore(2)


async def process_message(message_id: str, user_id: str) -> bool:
    """Claim once; retries re-read current NPC rows before applying facts."""
    task = None
    try:
        async with database.AsyncSessionLocal() as db:
            message = await db.get(ChatMessage, message_id)
            if message is None or message.role != "assistant":
                return False
            session = await db.get(GameSession, message.session_id)
            user = await db.get(User, user_id)
            if session is None or session.user_id != user_id or user is None:
                return False
            task = await queue.claim(db, message)
            if task is None:
                return False
            payload, player_name = await extraction_context(db, message, session)
            original_content = message.content
        result = await asyncio.wait_for(
            extract(user, session, message_id, payload), timeout=EXTRACTION_TIMEOUT
        )
        created = await _save(message_id, original_content, player_name, result, task["token"])
        if created is None:
            return False
        for npc_id in created:
            schedule_portrait(session.id, npc_id, user_id)
        return True
    except asyncio.CancelledError:
        if task:
            await _fail(message_id, task, interrupted=True)
        raise
    except Exception:
        logger.exception("NPC journal extraction failed for message %s", message_id)
        if task:
            await _fail(message_id, task)
        return False


async def _save(
    message_id: str, original_content: str, player_name: str, result: JournalExtraction, token: str
) -> list[str] | None:
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
        await db.commit()
        return created


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


async def _run(session_id: str, user_id: str) -> None:
    if _cooldowns.get(session_id, 0) > time.monotonic():
        return
    _cooldowns.pop(session_id, None)
    async with _capacity:
        await resume_pending(session_id, user_id)
        consecutive_failures = 0
        for _ in range(20):
            async with database.AsyncSessionLocal() as db:
                message_id = await queue.next_message(db, session_id)
            if message_id is None:
                return
            success = await process_message(message_id, user_id)
            consecutive_failures = 0 if success else consecutive_failures + 1
            if consecutive_failures >= 2:
                # An unavailable model must not consume an entire backlog on every UI poll.
                _cooldowns[session_id] = time.monotonic() + queue.RETRY_DELAY
                return
        _wakeups[session_id] = user_id


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
