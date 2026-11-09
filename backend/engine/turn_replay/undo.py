"""Undo the latest completed turn through its existing pre-turn SQL snapshot."""

from copy import deepcopy

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.engine.gameplay.agent_logic import AgentService
from backend.engine.turn_replay.service import ReplayUnavailableError, ready_snapshot
from backend.engine.turn_replay.snapshot import after, restore
from backend.models.chat import ChatMessage
from backend.models.game_session import GameSession
from backend.models.session_state import SessionState
from backend.models.turn_replay import TurnReplay

CHECKPOINT_REQUIRED = (
    "A safe pre-turn snapshot is not available for this response. "
    "Restore a Chronicles checkpoint from before this turn. Nothing was deleted."
)


async def undo_latest(db: AsyncSession, game: GameSession, message_id: str) -> int:
    """Caller authorizes debug access and owns the session lease and final commit."""
    session_id, user_id, avatar_id = game.id, game.user_id, game.avatar_id
    try:
        row = await ready_snapshot(db, session_id, message_id)
    except ReplayUnavailableError:
        raise ReplayUnavailableError(CHECKPOINT_REQUIRED) from None
    shared = await db.scalar(
        select(GameSession.id)
        .where(GameSession.avatar_id == avatar_id, GameSession.id != session_id)
        .limit(1)
    )
    if shared:
        raise ReplayUnavailableError(
            "This legacy avatar is shared. Use a session checkpoint instead."
        )
    before = deepcopy(row.before)
    state = await db.scalar(select(SessionState).where(SessionState.session_id == session_id))
    if (
        state is None
        or before.get("version") != 1
        or before.get("user_id") != user_id
        or (before.get("state") or {}).get("session_id") != session_id
        or (before.get("state") or {}).get("avatar_id") != avatar_id
        or (before.get("avatar") or {}).get("id") != avatar_id
    ):
        raise ReplayUnavailableError(CHECKPOINT_REQUIRED)
    # Debug visibility is a current UI preference, as in full turn regeneration.
    before["state"]["is_debug_enabled"] = state.is_debug_enabled
    count = await db.scalar(
        select(func.count())
        .select_from(ChatMessage)
        .where(ChatMessage.session_id == session_id, after(before["boundary"]))
    )
    await restore(db, session_id, before)
    restored = await db.scalar(select(SessionState).where(SessionState.session_id == session_id))
    if restored is None:
        raise ReplayUnavailableError(CHECKPOINT_REQUIRED)
    # A manual rewind must not restart a play-agent paused since the snapshot.
    AgentService.set_agent_active(restored, False)
    await db.execute(delete(TurnReplay).where(TurnReplay.session_id == session_id))
    return int(count or 0)
