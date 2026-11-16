"""Preserve interrupted visible prose without treating an uncommitted draft as canon."""

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.engine.turn_replay.control import story_message_filter
from backend.models.chat import ChatMessage
from backend.models.session_state import SessionState
from backend.models.turn_replay import TurnReplay

KEY = "__interrupted_narration__"
MAX_DRAFT_CHARS = 200000
RETRY_MESSAGE = "The previous turn did not finish. Retry the original action; do not submit 'Again' as a new action."


def receipt(manager: Any) -> dict:
    identifier = getattr(manager, "_committed_response_id", None)
    return (
        {"committed_assistant_id": identifier} if isinstance(identifier, str) and identifier else {}
    )


def observe(manager: Any, text: str) -> None:
    manager._visible_narration_draft = text[:MAX_DRAFT_CHARS]
    manager._visible_narration_truncated = len(text) > MAX_DRAFT_CHARS


def clear(state: Any) -> None:
    if KEY not in (state.entity_states or {}):
        return
    states = dict(state.entity_states or {})
    states.pop(KEY, None)
    state.entity_states = states


async def preserve(manager: Any) -> None:
    """Called under shield after recovery, when the original durable input remains."""
    text = getattr(manager, "_visible_narration_draft", "")
    if not text or getattr(manager, "_replaying", False):
        return
    row = await manager.db.get(TurnReplay, manager.game_id, populate_existing=True)
    if row is None or row.status != "pending":
        return
    state = await manager.db.scalar(
        select(SessionState)
        .where(SessionState.session_id == manager.game_id)
        .execution_options(populate_existing=True)
    )
    if state is None:
        return
    state.entity_states = {
        **(state.entity_states or {}),
        KEY: {
            "input_id": getattr(manager, "_vn_player_message_id", None),
            "action": row.input_text,
            "text": text,
            "truncated": bool(getattr(manager, "_visible_narration_truncated", False)),
        },
    }
    await manager.db.commit()


async def pending(db: AsyncSession, state: SessionState, *, busy: bool = False) -> dict | None:
    if busy:
        return None
    row = await db.get(TurnReplay, state.session_id)
    if row is None or row.status != "pending" or not row.input_text:
        return None
    message = await db.scalar(
        select(ChatMessage)
        .where(ChatMessage.session_id == state.session_id, story_message_filter())
        .order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc())
        .limit(1)
    )
    if message is None or message.role != "user" or message.content != row.input_text:
        return None
    draft = (state.entity_states or {}).get(KEY) or {}
    same_input = (
        isinstance(draft, dict)
        and draft.get("input_id") == message.id
        and draft.get("action") == row.input_text
    )
    return {
        "action": row.input_text,
        "message": RETRY_MESSAGE,
        "user_message_id": message.id,
        "draft": draft.get("text") if same_input else None,
        "draft_truncated": bool(same_input and draft.get("truncated")),
    }
