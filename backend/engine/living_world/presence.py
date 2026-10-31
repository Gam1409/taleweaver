"""Independent browser presence, without writing gameplay state during long turns."""

from copy import deepcopy
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.game_session import GameSession

PRESENCE_GRACE_SECONDS = 60
MAX_CLIENTS = 8


def heartbeat(raw: dict | None, client_id: str, active: bool, now: float) -> dict:
    result = deepcopy(raw or {"clients": {}, "offline_total": 0, "accounted_until": 0})
    clients = result["clients"]
    live = any(
        row["active"] and now - row["seen"] <= PRESENCE_GRACE_SECONDS for row in clients.values()
    )
    endpoints = [
        row["seen"] + (PRESENCE_GRACE_SECONDS if row["active"] else 0) for row in clients.values()
    ]
    if active and endpoints and not live:
        start = max(*endpoints, result["accounted_until"])
        result["offline_total"] += max(0, now - start)
        result["accounted_until"] = max(now, result["accounted_until"])
    old = clients.get(client_id)
    if not active and (old is None or not old["active"]):
        return result
    if client_id not in clients and len(clients) >= MAX_CLIENTS:
        removable = [
            key
            for key, value in clients.items()
            if not value["active"] or now - value["seen"] > PRESENCE_GRACE_SECONDS
        ]
        if not removable:
            raise HTTPException(409, "Too many active session connections.")
        del clients[min(removable, key=lambda key: clients[key]["seen"])]
    clients[client_id] = {"active": active, "seen": max(now, old["seen"] if old else now)}
    return result


async def record(
    db: AsyncSession, session_id: str, user_id: str, client_id: str, active: bool
) -> None:
    now = datetime.now(timezone.utc).timestamp()
    raw = await db.scalar(
        select(GameSession.living_world_presence).where(
            GameSession.id == session_id, GameSession.user_id == user_id
        )
    )
    changed = heartbeat(raw, client_id, active, now)
    # Release the read transaction before the conditional write (SQLite WAL).
    await db.commit()
    condition = (
        GameSession.living_world_presence == raw
        if raw is not None
        else GameSession.living_world_presence.is_(None)
    )
    result = await db.execute(
        update(GameSession)
        .where(GameSession.id == session_id, GameSession.user_id == user_id, condition)
        .values(living_world_presence=changed)
        .returning(GameSession.id)
    )
    if result.scalar_one_or_none() is None:
        await db.rollback()
        raise HTTPException(409, "Presence changed concurrently; retry the heartbeat.")
    await db.commit()
