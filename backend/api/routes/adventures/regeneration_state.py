"""Replace derived evidence atomically without undoing canonical game outcomes."""

from copy import deepcopy
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import set_attribute

from backend.engine.memory_rag.worker import mark_dirty
from backend.engine.npc_journal.retraction import retract_reply
from backend.engine.scene_illustrations.snapshots import (
    MAX_NARRATION,
    REGISTRY_KEY,
    content_hash,
    registry_of,
)
from backend.models.chat import ChatMessage
from backend.models.game_session import GameSession
from backend.models.memory_rag import MemoryIndexState, MemorySummary
from backend.models.session_state import SessionState
from backend.models.world_entity import WorldEntity


def refresh_visual_snapshot(state: SessionState, message: ChatMessage) -> None:
    states = deepcopy(state.entity_states or {})
    registry = registry_of(states)
    snapshot = registry["snapshots"].get(message.id)
    if not snapshot:
        return  # Never fabricate historical appearance from the current scene.
    snapshot.update(
        nonce=uuid4().hex,
        content_hash=content_hash(message),
        narration=message.content[:MAX_NARRATION],
    )
    registry["images"].pop(message.id, None)
    states[REGISTRY_KEY] = registry
    state.entity_states = states


async def refresh_evidence(db: AsyncSession, session: GameSession, message: ChatMessage) -> None:
    """Fence old workers, preserve NPC IDs/portraits, re-extract only this reply."""
    npcs = await db.scalars(
        select(WorldEntity).where(
            WorldEntity.session_id == session.id, WorldEntity.entity_type == "NPC"
        )
    )
    for npc in npcs:
        retract_reply(npc, message.id)
    if message.npc_journal is not None:
        set_attribute(message, "npc_journal", {"status": "pending", "attempts": 0})
    state = await db.scalar(
        select(SessionState)
        .where(SessionState.session_id == session.id)
        .execution_options(populate_existing=True)
    )
    if state is not None:
        refresh_visual_snapshot(state, message)
        await retract_chronicle(db, state, message)
    summaries = await db.scalars(
        select(MemorySummary).where(MemorySummary.session_id == session.id)
    )
    for summary in summaries:
        if message.id in (summary.source_message_ids or []):
            await db.delete(summary)
    await db.execute(
        update(MemoryIndexState)
        .where(MemoryIndexState.session_id == session.id)
        .values(
            epoch=MemoryIndexState.epoch + 1,
            lease_token=None,
            lease_until=None,
            status="pending",
        )
    )
    await mark_dirty(
        db,
        str(session.id),
        str(session.user_id),
        str(session.template_id) if session.template_id else None,
    )


async def retract_chronicle(db: AsyncSession, state: SessionState, message: ChatMessage) -> None:
    """Keep earlier chronicles; rebuild ones that may include replaced evidence."""
    history = state.compressed_history
    if not history:
        return
    marker = history.get("last_compressed_msg_id") if isinstance(history, dict) else None
    pending = history.get("pending_message_id") if isinstance(history, dict) else None
    if pending == message.id:
        state.compressed_history = {}
        return
    source = await db.get(ChatMessage, marker) if marker else None
    if (
        source is not None
        and source.session_id == message.session_id
        and (source.created_at, source.id) < (message.created_at, message.id)
    ):
        return
    # Unknown legacy provenance cannot establish that the summary is unaffected.
    # The full transcript remains available for normal background reconstruction.
    state.compressed_history = {}
