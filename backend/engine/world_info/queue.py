"""Atomic claims and source-aware fences for explicitly queued revisions."""

import time
from dataclasses import dataclass
from typing import Any, cast
from uuid import uuid4

from sqlalchemy import and_, or_, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import defer
from sqlalchemy.sql import ColumnElement
from sqlalchemy.sql.selectable import Exists

from backend.core import database
from backend.core.llm_deadlines import role_timeout
from backend.engine.memory_rag.persistence import retry_transaction
from backend.engine.world_info import limits
from backend.models.game_session import GameSession
from backend.models.user import User
from backend.models.world_info import WorldInfoRevision, WorldInfoSource

LEASE_GRACE_SECONDS = 120.0


class StaleJobError(RuntimeError):
    """A source control, replacement or another worker revoked this request."""


class CounterLimitError(ValueError):
    """The diagnostic counter cannot represent another logical request."""


@dataclass(frozen=True)
class Claim:
    revision_id: str
    source_id: str
    session_id: str
    user_id: str
    number: int
    content_hash: str
    cursor: int
    control_version: int
    run_token: str
    lease_token: str
    lease_seconds: float
    attempts: int


def current_source() -> Exists:
    return (
        select(WorldInfoSource.id)
        .join(GameSession, GameSession.id == WorldInfoSource.session_id)
        .where(
            WorldInfoSource.id == WorldInfoRevision.source_id,
            WorldInfoSource.current_revision == WorldInfoRevision.number,
            WorldInfoSource.session_id == WorldInfoRevision.session_id,
            WorldInfoSource.user_id == WorldInfoRevision.user_id,
            GameSession.user_id == WorldInfoRevision.user_id,
        )
        .exists()
    )


def eligible(now: float) -> ColumnElement[bool]:
    return or_(
        WorldInfoRevision.status == "queued",
        and_(
            WorldInfoRevision.status == "processing",
            or_(WorldInfoRevision.lease_until.is_(None), WorldInfoRevision.lease_until <= now),
        ),
    )


def fence(claim: Claim) -> tuple:
    return (
        WorldInfoRevision.id == claim.revision_id,
        WorldInfoRevision.source_id == claim.source_id,
        WorldInfoRevision.session_id == claim.session_id,
        WorldInfoRevision.user_id == claim.user_id,
        WorldInfoRevision.number == claim.number,
        WorldInfoRevision.content_hash == claim.content_hash,
        WorldInfoRevision.cursor == claim.cursor,
        WorldInfoRevision.control_version == claim.control_version,
        WorldInfoRevision.run_token == claim.run_token,
        WorldInfoRevision.lease_token == claim.lease_token,
        WorldInfoRevision.status == "processing",
        current_source(),
    )


@retry_transaction
async def claim_next(session_id: str, user_id: str) -> Claim | None:
    async with database.AsyncSessionLocal() as db:
        now = time.time()
        revision = await db.scalar(
            select(WorldInfoRevision)
            .options(defer(WorldInfoRevision.content))
            .where(
                WorldInfoRevision.session_id == session_id,
                WorldInfoRevision.user_id == user_id,
                WorldInfoRevision.run_token.is_not(None),
                eligible(now),
                current_source(),
            )
            .order_by(WorldInfoRevision.updated_at, WorldInfoRevision.id)
            .limit(1)
        )
        user = await db.get(User, user_id) if revision else None
        if revision is None or user is None:
            return None
        seconds = role_timeout(user, "generator") + LEASE_GRACE_SECONDS
        token = str(uuid4())
        changed = await db.execute(
            update(WorldInfoRevision)
            .where(
                WorldInfoRevision.id == revision.id,
                WorldInfoRevision.control_version == revision.control_version,
                WorldInfoRevision.run_token == revision.run_token,
                WorldInfoRevision.cursor == revision.cursor,
                eligible(now),
                current_source(),
            )
            .values(status="processing", lease_token=token, lease_until=now + seconds)
            .execution_options(synchronize_session=False)
        )
        if cast(CursorResult[Any], changed).rowcount != 1:
            return None
        claim = Claim(
            revision.id,
            revision.source_id,
            session_id,
            user_id,
            revision.number,
            revision.content_hash,
            revision.cursor,
            revision.control_version,
            str(revision.run_token),
            token,
            seconds,
            revision.attempts,
        )
        await db.commit()
        return claim


@retry_transaction
async def reserve_request(
    claim: Claim, *, ordinal: int = 0, lease_seconds: float | None = None
) -> None:
    """Persist each logical extraction request, including validation corrections."""
    target = claim.attempts + ordinal + 1
    if type(ordinal) is not int or ordinal < 0 or not 1 <= target <= limits.MAX_COUNTER:
        raise CounterLimitError("Source processing request counter is exhausted.")
    async with database.AsyncSessionLocal() as db:
        changed = await db.execute(
            update(WorldInfoRevision)
            .where(*fence(claim), WorldInfoRevision.attempts.in_([target - 1, target]))
            .values(
                attempts=target,
                lease_until=time.time() + (lease_seconds or claim.lease_seconds),
            )
            .execution_options(synchronize_session=False)
        )
        if cast(CursorResult[Any], changed).rowcount != 1:
            raise StaleJobError("Source processing is no longer current.")
        await db.commit()


@retry_transaction
async def release(claim: Claim, *, status: str = "queued", error: str | None = None) -> bool:
    async with database.AsyncSessionLocal() as db:
        values: dict[str, Any] = {
            "status": status,
            "lease_token": None,
            "lease_until": None,
            "last_error_code": error,
        }
        if status in {"failed", "cancelled", "review"}:
            values["run_token"] = None
        changed = await db.execute(
            update(WorldInfoRevision)
            .where(*fence(claim))
            .values(**values)
            .execution_options(synchronize_session=False)
        )
        await db.commit()
        return cast(CursorResult[Any], changed).rowcount == 1
