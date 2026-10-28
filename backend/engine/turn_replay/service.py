"""Capture, validate and recover the latest complete gameplay turn."""

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.engine.memory_rag.dirty_queue import queue_refresh
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
            .where(
                ChatMessage.session_id == session_id, ChatMessage.role.in_(["user", "assistant"])
            )
            .order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc())
            .limit(1)
        )
    ).first()


async def record_before(manager: Any, text: str) -> None:
    if (
        getattr(manager, "_replaying", False)
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
    data = await capture(manager.db, manager.game_id)
    row = await manager.db.get(TurnReplay, manager.game_id)
    if row is None:
        row = TurnReplay(session_id=manager.game_id, before=data, input_text=text, status="pending")
        manager.db.add(row)
    else:
        row.before, row.input_text, row.status = data, text, "pending"
        row.backup, row.assistant_id = None, None
    manager._turn_replay_recorded = True


async def finish(manager: Any) -> None:
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


async def begin(manager: Any, message_id: str) -> str:
    db: AsyncSession = manager.db
    sid: str = manager.game_id
    session = await db.get(GameSession, sid)
    if session is None or session.user_id != manager.user.id:
        raise ReplayUnavailableError("Session not found.")
    if session.status not in {"active", "completed", "game_over"}:
        raise ReplayUnavailableError("This session cannot replay a turn.")
    row = await db.get(TurnReplay, sid, populate_existing=True)
    message = await latest(db, sid)
    if (
        row is None
        or row.status != "ready"
        or row.assistant_id != message_id
        or message is None
        or message.id != message_id
    ):
        raise ReplayUnavailableError(
            "A pre-turn snapshot is not available for this response. Play a new turn first."
        )
    backup = await capture(db, sid, boundary=row.before["boundary"], backup=True)
    before, text = row.before, row.input_text
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
    if row is None or row.status != "replaying" or row.backup is None:
        return False
    backup = row.backup
    await restore(db, session_id, backup)
    row = await db.get(TurnReplay, session_id, populate_existing=True)
    if row is None:
        raise RuntimeError("Turn recovery record disappeared")
    row.status, row.backup = "ready", None
    await db.commit()
    queue_refresh(session_id, backup["user_id"])
    return True


async def recover_interrupted(db: AsyncSession) -> None:
    ids = list(
        await db.scalars(select(TurnReplay.session_id).where(TurnReplay.status == "replaying"))
    )
    for session_id in ids:
        await recover(db, session_id)


async def recover_owned(manager: Any) -> None:
    row = await manager.db.get(TurnReplay, manager.game_id)
    if row is None or row.status != "replaying":
        return
    session = await manager.db.get(GameSession, manager.game_id)
    if session is None or session.user_id != manager.user.id:
        raise ReplayUnavailableError("Session not found.")
    if await recover(manager.db, manager.game_id):
        await manager.db.refresh(manager.user)
        manager.state = manager.avatar = manager.adventure = None
