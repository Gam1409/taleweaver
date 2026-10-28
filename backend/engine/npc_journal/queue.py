"""Durable eligibility and claims for bounded, non-blocking journal extraction."""

import time
from uuid import uuid4

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased
from sqlalchemy.sql import ColumnElement
from sqlalchemy.sql.selectable import Exists

from backend.models.chat import ChatMessage

MAX_ATTEMPTS = 3
RETRY_DELAY = 60.0
LEASE_SECONDS = 180.0


def eligible(task: dict, now: float) -> bool:
    if int(task.get("attempts", 0)) >= MAX_ATTEMPTS:
        return False
    status = task.get("status")
    if status == "pending":
        return True
    if status == "failed":
        return float(task.get("retry_after", 0)) <= now
    return status == "running" and float(task.get("lease_until", 0)) <= now


def eligible_expression(now: float) -> ColumnElement[bool]:
    task = ChatMessage.npc_journal
    status = task["status"].as_string()
    return and_(
        func.coalesce(task["attempts"].as_integer(), 0) < MAX_ATTEMPTS,
        or_(
            status == "pending",
            and_(status == "failed", func.coalesce(task["retry_after"].as_float(), 0) <= now),
            and_(status == "running", func.coalesce(task["lease_until"].as_float(), 0) <= now),
        ),
    )


def active_session(session_id: str, now: float) -> Exists:
    other = aliased(ChatMessage)
    return (
        select(other.id)
        .where(
            other.session_id == session_id,
            other.npc_journal["status"].as_string() == "running",
            other.npc_journal["lease_until"].as_float() > now,
        )
        .exists()
    )


async def next_message(db: AsyncSession, session_id: str) -> str | None:
    now = time.time()
    await db.execute(
        update(ChatMessage)
        .where(
            ChatMessage.session_id == session_id,
            ChatMessage.npc_journal["status"].as_string() == "running",
            ChatMessage.npc_journal["attempts"].as_integer() >= MAX_ATTEMPTS,
            func.coalesce(ChatMessage.npc_journal["lease_until"].as_float(), 0) <= now,
        )
        .values(
            npc_journal={
                "status": "failed",
                "attempts": MAX_ATTEMPTS,
                "error": "Processing was interrupted repeatedly. Retry from Characters.",
            }
        )
    )
    await db.commit()
    return await db.scalar(
        select(ChatMessage.id)
        .where(
            ChatMessage.session_id == session_id,
            ChatMessage.role == "assistant",
            eligible_expression(now),
            ~active_session(session_id, now),
        )
        .order_by(ChatMessage.created_at, ChatMessage.id)
        .limit(1)
    )


async def next_retry_at(db: AsyncSession, session_id: str) -> float | None:
    """Wake failed/abandoned work without requiring the Characters dialog to stay open."""
    rows = await db.scalars(
        select(ChatMessage.npc_journal).where(
            ChatMessage.session_id == session_id,
            ChatMessage.npc_journal["status"].as_string().in_(["failed", "running"]),
            or_(
                ChatMessage.npc_journal["attempts"].as_integer() < MAX_ATTEMPTS,
                ChatMessage.npc_journal["status"].as_string() == "running",
            ),
        )
    )
    times = [
        float(task.get("lease_until" if task["status"] == "running" else "retry_after", 0))
        for task in rows
    ]
    return min(times) if times else None


async def claim(
    db: AsyncSession, message: ChatMessage, *, lease_seconds: float = LEASE_SECONDS
) -> dict | None:
    old = message.npc_journal or {}
    now = time.time()
    if not eligible(old, now):
        return None
    gaps = list(
        (
            await db.scalars(
                select(ChatMessage.id).where(
                    ChatMessage.session_id == message.session_id,
                    ChatMessage.role == "assistant",
                    ChatMessage.npc_journal["status"].as_string() == "failed",
                    or_(
                        ChatMessage.created_at < message.created_at,
                        and_(
                            ChatMessage.created_at == message.created_at,
                            ChatMessage.id < message.id,
                        ),
                    ),
                )
            )
        ).all()
    )
    task = {
        "status": "running",
        "attempts": int(old.get("attempts", 0)) + 1,
        "token": str(uuid4()),
        "lease_until": now + lease_seconds,
        "recovering": old.get("status") == "failed" or bool(old.get("recovering")),
        "gaps": gaps,
    }
    updated = await db.execute(
        update(ChatMessage)
        .where(
            ChatMessage.id == message.id,
            ChatMessage.npc_journal == old,
            ~active_session(message.session_id, now),
        )
        .values(npc_journal=task)
        .execution_options(synchronize_session=False)
    )
    if updated.rowcount != 1:
        await db.rollback()
        return None
    await db.commit()
    return task


async def fence(db: AsyncSession, message: ChatMessage, token: str) -> bool:
    task = message.npc_journal or {}
    if task.get("status") != "running" or task.get("token") != token:
        return False
    result = await db.execute(
        update(ChatMessage)
        .where(ChatMessage.id == message.id, ChatMessage.npc_journal == task)
        .values(npc_journal=task)
        .execution_options(synchronize_session=False)
    )
    return result.rowcount == 1


async def requeue_dependents(db: AsyncSession, recovered: ChatMessage) -> None:
    """Replay facts extracted without an earlier introduction after it is recovered.

    Stored observations are evidence-keyed and sorted by source time; replay cannot
    duplicate entries or make an old observation supersede a newer one.
    """
    messages = (
        await db.scalars(
            select(ChatMessage).where(
                ChatMessage.session_id == recovered.session_id,
                ChatMessage.npc_journal["status"].as_string() == "done",
            )
        )
    ).all()
    for message in messages:
        task = message.npc_journal or {}
        if recovered.id not in (task.get("gaps") or []):
            continue
        message.npc_journal = {
            "status": "pending",
            "attempts": 0,
            "gaps": [identifier for identifier in task["gaps"] if identifier != recovered.id],
        }
