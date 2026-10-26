"""Best-effort background portraits; a failed image never removes a learned NPC."""

import asyncio
import logging

from sqlalchemy import select, update

from backend.core import database
from backend.engine.memory_rag.persistence import retry_transaction
from backend.engine.npc_journal.records import JOURNAL_KEY, journal_of
from backend.engine.session_portraits import SessionPortraitRequest, regenerate_session_portrait
from backend.models.user import User
from backend.models.world_entity import WorldEntity

logger = logging.getLogger(__name__)
_tasks: dict[tuple[str, str], asyncio.Task] = {}
_capacity = asyncio.Semaphore(1)


def portrait_status(session_id: str, npc_id: str, saved: str | None) -> str | None:
    if saved == "running" and (session_id, npc_id) not in _tasks:
        return "interrupted"
    return saved


async def resume_pending(session_id: str, user_id: str) -> None:
    async with database.AsyncSessionLocal() as db:
        npcs = (
            await db.scalars(
                select(WorldEntity).where(
                    WorldEntity.session_id == session_id,
                    WorldEntity.metadata_json[JOURNAL_KEY]["portrait_status"].as_string()
                    == "pending",
                )
            )
        ).all()
        for npc in npcs:
            schedule_portrait(session_id, npc.id, user_id)


@retry_transaction
async def _try_mark(session_id: str, npc_id: str, status: str) -> tuple[bool, bool]:
    async with database.AsyncSessionLocal() as db:
        npc = await db.scalar(
            select(WorldEntity).where(
                WorldEntity.session_id == session_id,
                WorldEntity.id == npc_id,
            )
        )
        if npc is None:
            return True, False
        before = npc.metadata_json
        previous_image = npc.image_url
        journal = journal_of(npc)
        journal["portrait_status"] = "ready" if npc.image_url else status
        updated = await db.execute(
            update(WorldEntity)
            .where(
                WorldEntity.session_id == session_id,
                WorldEntity.id == npc_id,
                WorldEntity.metadata_json == before,
                WorldEntity.image_url == previous_image,
            )
            .values(metadata_json={**(before or {}), JOURNAL_KEY: journal})
            .execution_options(synchronize_session=False)
        )
        if updated.rowcount != 1:
            return False, False
        await db.commit()
        return True, not bool(previous_image)


async def _mark(session_id: str, npc_id: str, status: str) -> bool:
    for _attempt in range(3):
        saved, needs_image = await _try_mark(session_id, npc_id, status)
        if saved:
            return needs_image
    raise RuntimeError("The NPC changed repeatedly while saving portrait status.")


async def _run(session_id: str, npc_id: str, user_id: str) -> None:
    try:
        async with _capacity:
            if not await _mark(session_id, npc_id, "running"):
                return
            async with database.AsyncSessionLocal() as db:
                user = await db.get(User, user_id)
                if user is None:
                    return
                await regenerate_session_portrait(
                    session_id, SessionPortraitRequest(target_id=npc_id), db, user
                )
        await _mark(session_id, npc_id, "ready")
    except asyncio.CancelledError:
        # A provider may still be running; do not automatically pay for a second image.
        try:
            await _mark(session_id, npc_id, "interrupted")
        except Exception:
            logger.exception(
                "Could not save interrupted portrait status for %s/%s", session_id, npc_id
            )
        raise
    except Exception:
        logger.exception("Automatic NPC portrait failed for session %s NPC %s", session_id, npc_id)
        await _mark(session_id, npc_id, "failed")


def schedule_portrait(session_id: str, npc_id: str, user_id: str) -> None:
    key = (session_id, npc_id)
    if key in _tasks:
        return
    task = asyncio.create_task(_run(session_id, npc_id, user_id))
    _tasks[key] = task
    task.add_done_callback(lambda done: _finish(key, done))


def _finish(key: tuple[str, str], task: asyncio.Task) -> None:
    _tasks.pop(key, None)
    if not task.cancelled() and task.exception():
        logger.error("NPC portrait task failed", exc_info=task.exception())


async def shutdown() -> None:
    tasks = list(_tasks.values())
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
