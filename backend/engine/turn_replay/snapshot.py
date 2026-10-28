"""Explicit session-scoped SQL snapshots; never copy provider secrets or templates."""

from copy import deepcopy
from datetime import datetime
from typing import Any, cast

from fastapi.encoders import jsonable_encoder
from sqlalchemy import DateTime, Table, and_, delete, insert, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.avatar import Avatar
from backend.models.chat import ChatMessage
from backend.models.game_session import GameSession
from backend.models.memory_rag import MemoryIndexState, MemorySummary
from backend.models.session_checkpoint import SessionCheckpoint
from backend.models.session_state import SessionState
from backend.models.user import User
from backend.models.world_entity import WorldEntity, WorldExit, WorldScene
from backend.models.world_map import WorldMap

# Restore full session-owned rows, including mutable NPC metadata, inventories,
# generated places, exits, map discovery, checkpoints and canonical summaries.
SCOPED = (WorldEntity, WorldExit, WorldScene, WorldMap, SessionCheckpoint, MemorySummary)
SESSION_FIELDS = (
    "status",
    "status_note",
    "content_language",
    "adventure_title",
    "adventure_image_url",
)
USER_FIELDS = ("earned_awards", "game_log")


def decoded(table: Any, values: dict) -> dict:
    result = deepcopy(values)
    for column in table.columns:
        if isinstance(column.type, DateTime) and isinstance(result.get(column.name), str):
            result[column.name] = datetime.fromisoformat(result[column.name])
    return result


def after(boundary: dict | None) -> Any:
    if boundary is None:
        return True
    stamp = datetime.fromisoformat(boundary["created_at"])
    return or_(
        ChatMessage.created_at > stamp,
        and_(ChatMessage.created_at == stamp, ChatMessage.id > boundary["id"]),
    )


async def rows(db: AsyncSession, model: Any, condition: Any) -> list[dict]:
    return [
        dict(row) for row in (await db.execute(select(model.__table__).where(condition))).mappings()
    ]


async def capture(
    db: AsyncSession, session_id: str, *, boundary: dict | None = None, backup: bool = False
) -> dict:
    await db.flush()
    session = (await rows(db, GameSession, GameSession.id == session_id))[0]
    state = (await rows(db, SessionState, SessionState.session_id == session_id))[0]
    avatar = (await rows(db, Avatar, Avatar.id == state["avatar_id"]))[0]
    if not backup:
        last = await db.scalar(
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc())
            .limit(1)
        )
        boundary = {"id": last.id, "created_at": last.created_at.isoformat()} if last else None
    user = (await rows(db, User, User.id == session["user_id"]))[0]
    tables = {
        model.__tablename__: await rows(db, model, model.session_id == session_id)
        for model in SCOPED
    }
    tasks = (
        await db.execute(
            select(ChatMessage.id, ChatMessage.npc_journal).where(
                ChatMessage.session_id == session_id
            )
        )
    ).all()
    return dict(
        jsonable_encoder(
            {
                "version": 1,
                "boundary": boundary,
                "state": state,
                "avatar": avatar,
                "session": {key: session[key] for key in SESSION_FIELDS},
                "user_id": session["user_id"],
                "user": {
                    key: [
                        entry for entry in user[key] or [] if entry.get("session_id") == session_id
                    ]
                    for key in USER_FIELDS
                },
                "tables": tables,
                "journal_tasks": {key: value for key, value in tasks},
                "messages": await rows(
                    db, ChatMessage, and_(ChatMessage.session_id == session_id, after(boundary))
                )
                if backup
                else [],
            }
        )
    )


async def restore(db: AsyncSession, session_id: str, snapshot: dict) -> None:
    """Caller owns one write transaction and the foreground/session lease."""
    if snapshot.get("version") != 1 or snapshot["state"]["session_id"] != session_id:
        raise ValueError("Invalid turn snapshot")
    await db.execute(
        delete(ChatMessage).where(ChatMessage.session_id == session_id, after(snapshot["boundary"]))
    )
    for model in SCOPED:
        await db.execute(delete(model).where(model.session_id == session_id))
        data = snapshot["tables"][model.__tablename__]
        if data:
            await db.execute(
                insert(cast(Table, model.__table__)),
                [decoded(model.__table__, row) for row in data],
            )
    await db.execute(
        update(cast(Table, SessionState.__table__))
        .where(SessionState.session_id == session_id)
        .values(**decoded(SessionState.__table__, snapshot["state"]))
    )
    await db.execute(
        update(cast(Table, Avatar.__table__))
        .where(Avatar.id == snapshot["avatar"]["id"])
        .values(**decoded(Avatar.__table__, snapshot["avatar"]))
    )
    await db.execute(
        update(cast(Table, GameSession.__table__))
        .where(GameSession.id == session_id)
        .values(**snapshot["session"])
    )
    if snapshot["messages"]:
        await db.execute(
            insert(cast(Table, ChatMessage.__table__)),
            [decoded(ChatMessage.__table__, row) for row in snapshot["messages"]],
        )
    for message_id, task in snapshot["journal_tasks"].items():
        if isinstance(task, dict) and task.get("status") == "running":
            restored_task = {"status": "pending", "attempts": 0}
        else:
            restored_task = task
        await db.execute(
            update(ChatMessage)
            .where(ChatMessage.id == message_id, ChatMessage.session_id == session_id)
            .values(npc_journal=restored_task)
            .execution_options(synchronize_session=False)
        )
    user = (await rows(db, User, User.id == snapshot["user_id"]))[0]
    fields = {
        key: [entry for entry in user[key] or [] if entry.get("session_id") != session_id]
        + snapshot["user"][key]
        for key in USER_FIELDS
    }
    await db.execute(
        update(cast(Table, User.__table__)).where(User.id == snapshot["user_id"]).values(**fields)
    )
    # Never restore an old epoch: late embeddings must remain fenced out.
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
    db.expire_all()
