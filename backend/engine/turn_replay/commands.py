"""Protect command-side commits with the same durable recovery used by narration."""

from typing import Any

from sqlalchemy import select

from backend.engine.turn_replay.control import is_debug_toggle
from backend.engine.turn_replay.snapshot import capture
from backend.models.game_session import GameSession
from backend.models.turn_replay import TurnReplay


async def prepare_command(manager: Any, text: str) -> None:
    if is_debug_toggle(text):
        return
    if not text.startswith("/") or text.lower().startswith("/say "):
        return
    if getattr(manager, "_replaying", False):
        return
    shared = await manager.db.scalar(
        select(GameSession.id)
        .where(GameSession.avatar_id == manager.avatar.id, GameSession.id != manager.game_id)
        .limit(1)
    )
    if shared:
        raise ValueError("Copy this legacy session before using commands; its character is shared.")
    snapshot = await capture(manager.db, manager.game_id)
    row = await manager.db.get(TurnReplay, manager.game_id)
    if row is None:
        row = TurnReplay(session_id=manager.game_id)
        manager.db.add(row)
    row.before = snapshot
    row.backup = snapshot
    row.input_text = text
    row.status = "executing"
    row.assistant_id = None
    manager._command_recovery = True
    manager._recoverable_turn = True
    manager._turn_replay_recorded = True
    await manager.db.commit()
