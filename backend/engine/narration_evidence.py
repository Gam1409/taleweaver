"""Replace derived evidence atomically without undoing canonical game outcomes."""

from copy import deepcopy
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import set_attribute

from backend.engine.chpm.state import retract as retract_chpm
from backend.engine.living_world.dialogue_memory import retract as retract_intentions
from backend.engine.memory_rag.worker import mark_dirty
from backend.engine.npc_journal.retraction import retract_reply
from backend.engine.physical_conditions.visuals import retract as retract_visual_conditions
from backend.engine.scene_continuity.lifecycle import retract as retract_scene_continuity
from backend.engine.scene_illustrations.snapshots import (
    MAX_NARRATION,
    REGISTRY_KEY,
    content_hash,
    registry_of,
)
from backend.engine.scene_staging import props
from backend.engine.scene_staging.provenance import retract
from backend.engine.visual_plan_lifecycle import reset
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
    facts = snapshot.get("visible_facts") or {}
    if "staging_status" in facts:
        facts["staging_status"] = "unconfirmed"
    for person in facts.get("characters", []):
        person.pop("posture", None)
        person.pop("placement", None)
    facts.pop("props", None)
    facts.pop("explicit", None)
    facts.pop("visible_action", None)
    facts.pop("visible_actions", None)
    facts.pop("scene_facts", None)
    facts.pop("physical_conditions", None)
    snapshot.pop("staging_sources", None)
    snapshot.update(
        nonce=uuid4().hex,
        source_revision_id=message.revision_id,
        content_hash=content_hash(message),
        narration=message.content[:MAX_NARRATION],
    )
    registry["images"].pop(message.id, None)
    states[REGISTRY_KEY] = registry
    state.entity_states = reset(states)


async def refresh_evidence(db: AsyncSession, session: GameSession, message: ChatMessage) -> None:
    """Fence old workers, preserve NPC IDs/portraits, re-extract only this reply."""
    await retract_evidence(db, session, message.id, message=message)


async def retract_evidence(
    db: AsyncSession,
    session: GameSession,
    message_id: str,
    *,
    message: ChatMessage | None = None,
) -> None:
    """Reuse source-owner retraction when a retained checkpoint source changed or vanished."""
    npcs = await db.scalars(
        select(WorldEntity).where(
            WorldEntity.session_id == session.id, WorldEntity.entity_type == "NPC"
        )
    )
    for npc in npcs:
        retract_reply(npc, message_id)
    if message is not None and message.npc_journal is not None:
        set_attribute(message, "npc_journal", {"status": "pending", "attempts": 0})
    state = await db.scalar(
        select(SessionState)
        .where(SessionState.session_id == session.id)
        .execution_options(populate_existing=True)
    )
    if state is not None:
        retract_chpm(state, message_id)
        retract_scene_continuity(state, message_id)
        retract_visual_conditions(state, message_id)
        retract(state, message_id)
        retract_intentions(state, message_id)
        props.retract(state, message_id)
        direction = (state.entity_states or {}).get("__vn_story_direction__") or {}
        if (direction.get("focus") or {}).get("message_id") == message_id:
            direction = {key: value for key, value in direction.items() if key != "focus"}
            state.entity_states = {
                **(state.entity_states or {}),
                "__vn_story_direction__": direction,
            }
        await _refresh_source_context(db, state, message_id, message)
    summaries = await db.scalars(
        select(MemorySummary).where(MemorySummary.session_id == session.id)
    )
    for summary in summaries:
        if message_id in (summary.source_message_ids or []):
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


async def _refresh_source_context(
    db: AsyncSession, state: SessionState, message_id: str, message: ChatMessage | None
) -> None:
    if message is not None:
        refresh_visual_snapshot(state, message)
        await retract_chronicle(db, state, message)
        return
    states = deepcopy(state.entity_states or {})
    registry = registry_of(states)
    registry["snapshots"].pop(message_id, None)
    registry["images"].pop(message_id, None)
    states[REGISTRY_KEY] = registry
    state.entity_states = reset(states)
    # An absent source cannot prove that the historical chronicle is unaffected.
    state.compressed_history = {}


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
