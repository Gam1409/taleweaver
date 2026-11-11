"""Capture, validate and recover the latest complete gameplay turn."""

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.engine.memory_rag.dirty_queue import queue_refresh
from backend.engine.turn_replay.control import story_message_filter
from backend.engine.turn_replay.snapshot import capture, restore
from backend.models.chat import ChatMessage
from backend.models.game_session import GameSession
from backend.models.turn_replay import TurnReplay


class ReplayUnavailableError(ValueError):
    """Safe user-facing refusal before a replay starts."""


async def latest(db: AsyncSession, session_id: str) -> ChatMessage | None:
    return (
        await db.scalars(
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id, story_message_filter())
            .order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc())
            .limit(1)
        )
    ).first()


async def record_before(manager: Any, text: str) -> None:
    if (
        getattr(manager, "_replaying", False)
        or getattr(manager, "_command_recovery", False)
        or not text
        or (text.startswith("/") and not text.lower().startswith("/say "))
        or manager.adventure.is_adventure_generator
    ):
        return
    shared = await manager.db.scalar(
        select(GameSession.id)
        .where(GameSession.avatar_id == manager.avatar.id, GameSession.id != manager.game_id)
        .limit(1)
    )
    if shared:
        return  # Legacy shared avatars cannot be rewound independently.
    from backend.engine.turn_replay import debug_history

    await debug_history.record_before(manager, text)
    data = await capture(manager.db, manager.game_id)
    row = await manager.db.get(TurnReplay, manager.game_id)
    if row is None:
        row = TurnReplay(session_id=manager.game_id, before=data, input_text=text, status="pending")
        manager.db.add(row)
    else:
        row.before, row.input_text, row.status = data, text, "pending"
        row.backup, row.assistant_id = None, None
    manager._turn_replay_recorded = True


async def record_input(manager: Any, text: str) -> ChatMessage:
    """Reuse a failed turn's durable input instead of duplicating it on retry."""
    row = await manager.db.get(TurnReplay, manager.game_id)
    message = await latest(manager.db, manager.game_id)
    if (
        row is not None
        and row.status == "pending"
        and row.input_text == text
        and message is not None
        and message.role == "user"
        and message.content == text
    ):
        manager._turn_replay_recorded = True
        return message
    await record_before(manager, text)
    saved: ChatMessage = await manager._save_chat_message("user", text)
    return saved


async def finish(manager: Any) -> None:
    if getattr(manager, "_command_recovery", False):
        row = await manager.db.get(TurnReplay, manager.game_id)
        if row is not None:
            row.status, row.backup, row.assistant_id = "command_complete", None, None
            await manager.db.commit()
        return
    if not getattr(manager, "_turn_replay_recorded", False) and not getattr(
        manager, "_replaying", False
    ):
        return
    message = await latest(manager.db, manager.game_id)
    row = await manager.db.get(TurnReplay, manager.game_id, populate_existing=True)
    if row is None or message is None or message.role != "assistant":
        if getattr(manager, "_replaying", False):
            raise ValueError("The turn has no completed response")
        return  # A non-narrative turn must not become replayable.
    row.assistant_id, row.status, row.backup = message.id, "ready", None
    await manager.db.commit()


async def mark_committed(manager: Any, message: ChatMessage) -> None:
    """Fence the canonical response in its state transaction, before transport/payload work."""
    if getattr(manager, "_replaying", False):
        return
    if not (
        getattr(manager, "_turn_replay_recorded", False) or getattr(manager, "_replaying", False)
    ):
        return
    await manager.db.flush()
    row = await manager.db.get(TurnReplay, manager.game_id)
    if row is None:
        raise RuntimeError("The turn recovery record is missing")
    row.assistant_id, row.status, row.backup = message.id, "ready", None


async def ready_snapshot(db: AsyncSession, session_id: str, message_id: str) -> TurnReplay:
    """Validate the exact latest completed response before a rewind or undo."""
    row = await db.get(TurnReplay, session_id, populate_existing=True)
    message = await latest(db, session_id)
    if (
        row is None
        or row.status != "ready"
        or row.assistant_id != message_id
        or message is None
        or message.is_debug
        or message.id != message_id
    ):
        raise ReplayUnavailableError(
            "A pre-turn snapshot is not available for this response. Play a new turn first."
        )
    return row


async def begin(manager: Any, message_id: str) -> str:
    db: AsyncSession = manager.db
    sid: str = manager.game_id
    session = await db.get(GameSession, sid)
    if session is None or session.user_id != manager.user.id:
        raise ReplayUnavailableError("Session not found.")
    if session.status not in {"active", "completed", "game_over"}:
        raise ReplayUnavailableError("This session cannot replay a turn.")
    row = await ready_snapshot(db, sid, message_id)
    backup = await capture(db, sid, boundary=row.before["boundary"], backup=True)
    # Debug visibility is a current UI preference, not a consequence to rewind.
    before = {
        **row.before,
        "state": {**row.before["state"], "is_debug_enabled": backup["state"]["is_debug_enabled"]},
    }
    text = row.input_text
    row.backup, row.status = backup, "replaying"
    await db.commit()  # Durable recovery record precedes the destructive rewind.
    manager._replaying = True
    await restore(db, sid, before)
    await db.commit()
    await db.refresh(manager.user)
    manager.state = manager.avatar = manager.adventure = None
    return text


async def recover(db: AsyncSession, session_id: str) -> bool:
    row = await db.get(TurnReplay, session_id, populate_existing=True)
    if row is None or row.status not in {"replaying", "executing"} or row.backup is None:
        return False
    replaying = row.status == "replaying"
    backup = row.backup
    await restore(db, session_id, backup)
    row = await db.get(TurnReplay, session_id, populate_existing=True)
    if row is None:
        raise RuntimeError("Turn recovery record disappeared")
    row.status, row.backup = ("ready" if replaying else "pending"), None
    await db.commit()
    queue_refresh(session_id, backup["user_id"])
    return True


async def recover_interrupted(db: AsyncSession) -> None:
    ids = list(
        await db.scalars(
            select(TurnReplay.session_id).where(TurnReplay.status.in_(["replaying", "executing"]))
        )
    )
    for session_id in ids:
        await recover(db, session_id)


async def recover_owned(manager: Any) -> None:
    row = await manager.db.get(TurnReplay, manager.game_id)
    if row is None or row.status not in {"replaying", "executing"}:
        return
    session = await manager.db.get(GameSession, manager.game_id)
    if session is None or session.user_id != manager.user.id:
        raise ReplayUnavailableError("Session not found.")
    if await recover(manager.db, manager.game_id):
        await manager.db.refresh(manager.user)
        manager.state = manager.avatar = manager.adventure = None
