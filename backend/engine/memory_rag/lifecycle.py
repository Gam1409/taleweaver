"""Keep canonical memory portable and fence derived work across timeline changes."""

import asyncio
import logging
from copy import deepcopy
from typing import Any

from sqlalchemy import delete, select, update

from backend.engine.memory_rag.documents import collect_documents, sources_hash, summary_sources
from backend.engine.memory_rag.store import LanceMemoryStore
from backend.models.game_session import GameSession
from backend.models.memory_rag import MemoryIndexState, MemorySummary
from backend.models.session_state import SessionState

MEMORY_FIELDS = (
    "world_memories",
    "world_rumors",
    "compressed_history",
    "enable_history_compression",
)
logger = logging.getLogger(__name__)


async def purge_session_memory(db: Any, user_id: str, session_id: str) -> None:
    """Fence and remove this owner's derived memory before the session is deleted."""
    owned = await db.scalar(
        select(GameSession.id).where(GameSession.id == session_id, GameSession.user_id == user_id)
    )
    if owned is None:
        return
    await db.execute(
        delete(MemoryIndexState).where(
            MemoryIndexState.session_id == session_id, MemoryIndexState.user_id == user_id
        )
    )
    await db.execute(
        delete(MemorySummary).where(
            MemorySummary.session_id == session_id, MemorySummary.user_id == user_id
        )
    )
    try:
        await asyncio.wait_for(LanceMemoryStore().delete_session(user_id, session_id), timeout=2)
    except Exception:
        logger.warning("Optional vector cleanup unavailable for deleted session %s", session_id)


async def detach_template_memory(db: Any, template_id: str) -> None:
    """Keep session memories while invalidating their old template-routing metadata."""
    await db.execute(
        update(MemoryIndexState)
        .where(MemoryIndexState.template_id == template_id)
        .values(
            template_id=None,
            epoch=MemoryIndexState.epoch + 1,
            desired_revision=MemoryIndexState.desired_revision + 1,
            lease_token=None,
            lease_until=None,
            status="pending",
        )
    )


def memory_snapshot(state: Any) -> dict:
    return {field: deepcopy(getattr(state, field, None)) for field in MEMORY_FIELDS}


def restore_memory(state: Any, snapshot: dict, message_ids: dict | None = None) -> None:
    """Old checkpoints cannot establish future memories; absent fields reset safely."""
    for field in MEMORY_FIELDS:
        default = True if field == "enable_history_compression" else None
        setattr(state, field, deepcopy(snapshot.get(field, default)))
    if not message_ids or not isinstance(state.compressed_history, dict):
        return
    history = dict(state.compressed_history)
    marker = history.get("last_compressed_msg_id")
    if marker:
        history["last_compressed_msg_id"] = message_ids.get(marker)
    pending = history.get("pending_message_id")
    if pending:
        history["pending_message_id"] = message_ids.get(pending)
    state.compressed_history = history


async def invalidate_memory(db: Any, session_id: str) -> None:
    """Called in the same SQL transaction as rewind; stale writes lose their lease."""
    await db.execute(
        update(MemoryIndexState)
        .where(MemoryIndexState.session_id == session_id)
        .values(
            epoch=MemoryIndexState.epoch + 1,
            desired_revision=MemoryIndexState.desired_revision + 1,
            lease_token=None,
            lease_until=None,
            status="pending",
        )
    )
    await db.execute(delete(MemorySummary).where(MemorySummary.session_id == session_id))


async def export_summaries(db: Any, session_id: str) -> list[dict]:
    rows = await db.scalars(select(MemorySummary).where(MemorySummary.session_id == session_id))
    return [
        {
            "layer": row.layer,
            "npc_id": row.npc_id,
            "scene_id": row.scene_id,
            "text": row.text,
            "source_message_ids": row.source_message_ids,
            "source_hash": row.source_hash,
        }
        for row in rows
    ]


async def copy_session_summaries(
    db: Any, source_session_id: str, target_session_id: str, user_id: str, message_ids: dict
) -> None:
    state = await db.scalar(
        select(SessionState).where(SessionState.session_id == target_session_id)
    )
    if state is None:
        return
    await import_summaries(
        db, state, user_id, await export_summaries(db, source_session_id), message_ids
    )


async def import_summaries(
    db: Any, state: Any, user_id: str, rows: list[dict], message_ids: dict[str, str]
) -> None:
    await db.flush()
    documents = await collect_documents(db, state, user_id)
    allowed = {"npc_summary", "scene_summary", "story_summary"}
    for row in rows:
        if not isinstance(row, dict) or row.get("layer") not in allowed or not row.get("text"):
            continue
        old_ids = row.get("source_message_ids") or []
        if not old_ids or not all(source in message_ids for source in old_ids):
            continue
        ids = [message_ids[source] for source in old_ids]
        sources = summary_sources(documents, row["layer"], row.get("npc_id"), row.get("scene_id"))
        available = {mid for doc in sources for mid in doc.source_message_ids}
        if not set(ids) <= available:
            continue
        db.add(
            MemorySummary(
                session_id=state.session_id,
                user_id=user_id,
                layer=row["layer"],
                npc_id=row.get("npc_id"),
                scene_id=row.get("scene_id"),
                text=str(row["text"])[:6000],
                source_message_ids=ids,
                source_hash=sources_hash(sources, ids),
            )
        )
