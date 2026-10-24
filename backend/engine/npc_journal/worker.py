"""Durable per-narration work; background failures never roll back a player's turn."""

import asyncio
import logging

from sqlalchemy import select

from backend.core import database
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
_capacity = asyncio.Semaphore(2)


async def process_message(message_id: str, user_id: str) -> bool:
    """Single-worker entry point; retries re-read current NPC rows before applying facts."""
    async with database.AsyncSessionLocal() as db:
        message = await db.get(ChatMessage, message_id)
        if message is None or message.role != "assistant":
            return False
        session = await db.get(GameSession, message.session_id)
        user = await db.get(User, user_id)
        if session is None or session.user_id != user_id or user is None:
            return False
        task = message.npc_journal or {}
        if task.get("status") not in ("pending", "running"):
            return False
        attempts = int(task.get("attempts", 0)) + 1
        if attempts > 3:
            message.npc_journal = {
                "status": "failed",
                "attempts": attempts,
                "error": "Processing was interrupted repeatedly. Retry from Characters.",
            }
            await db.commit()
            return False
        message.npc_journal = {"status": "running", "attempts": attempts}
        payload, player_name = await extraction_context(db, message, session)
        original_content = message.content
        await db.commit()
    try:
        result = await asyncio.wait_for(
            extract(user, session, message_id, payload), timeout=EXTRACTION_TIMEOUT
        )
        created = await _save(message_id, original_content, player_name, result)
        for npc_id in created:
            schedule_portrait(session.id, npc_id, user_id)
        return True
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("NPC journal extraction failed for message %s", message_id)
        await _fail(message_id, attempts)
        return False


async def _save(
    message_id: str, original_content: str, player_name: str, result: JournalExtraction
) -> list[str]:
    async with database.AsyncSessionLocal() as db:
        message = await db.get(ChatMessage, message_id)
        if message is None or message.content != original_content:
            return []
        if (message.npc_journal or {}).get("status") == "done":
            return []
        created = await apply_extraction(db, message, result, player_name)
        message.npc_journal = {**(message.npc_journal or {}), "status": "done"}
        await db.commit()
        return created


async def _fail(message_id: str, attempts: int) -> None:
    async with database.AsyncSessionLocal() as db:
        message = await db.get(ChatMessage, message_id)
        if message is None:
            return
        message.npc_journal = {
            "status": "failed",
            "attempts": attempts,
            "error": "Could not update character knowledge. Check the Small / Utility model and retry.",
        }
        await db.commit()


async def _run(session_id: str, user_id: str) -> None:
    async with _capacity:
        await resume_pending(session_id, user_id)
        # Bound each wake-up. The next session poll resumes any remaining work.
        for _ in range(20):
            async with database.AsyncSessionLocal() as db:
                message_id = await db.scalar(
                    select(ChatMessage.id)
                    .where(
                        ChatMessage.session_id == session_id,
                        ChatMessage.role == "assistant",
                        # Preserve story order: later facts wait until a failed introduction is retried.
                        ChatMessage.npc_journal["status"]
                        .as_string()
                        .in_(["pending", "running", "failed"]),
                    )
                    .order_by(ChatMessage.created_at, ChatMessage.id)
                    .limit(1)
                )
            if message_id is None or not await process_message(message_id, user_id):
                return


def schedule(session_id: str, user_id: str) -> None:
    if session_id in _tasks:
        return
    task = asyncio.create_task(_run(session_id, user_id))
    _tasks[session_id] = task
    task.add_done_callback(lambda done: _finish(session_id, done))


def _finish(session_id: str, task: asyncio.Task) -> None:
    _tasks.pop(session_id, None)
    if not task.cancelled() and task.exception():
        logger.error("NPC journal task failed", exc_info=task.exception())


async def shutdown() -> None:
    from backend.engine.npc_journal.portraits import shutdown as stop_portraits

    tasks = list(_tasks.values())
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    await stop_portraits()
