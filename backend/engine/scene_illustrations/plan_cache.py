"""Bounded derived JSON cache with short session leases and revision/rewind fences."""

import json
from collections.abc import Callable
from copy import deepcopy
from typing import Any, TypeVar, cast

from fastapi import HTTPException
from sqlalchemy import update
from sqlalchemy.engine import CursorResult

from backend.core import database
from backend.engine.visual_novel.concurrency import SessionBusyError, session_write_lease
from backend.engine.visual_novel.config import read_settings
from backend.engine.visual_plan_lifecycle import KEY, reset
from backend.models.session_state import SessionState

from .context import owned_context, require_snapshot
from .visual_plan import fingerprint

T = TypeVar("T")

MAX_ENTRIES = 8
MAX_BYTES = 2 * 1024 * 1024


def token(state: Any, message: Any, snapshot: dict) -> str:
    settings = read_settings(state)
    return fingerprint(
        {
            "epoch": (state.entity_states or {}).get(KEY, {}).get("epoch"),
            "message_id": message.id,
            "revision": message.revision_id,
            "source": {
                key: snapshot.get(key) for key in ("nonce", "content_hash", "visible_facts")
            },
            "settings": [
                settings.visual_preparation,
                settings.visual_audit,
                settings.visual_audit_failure,
            ],
        }
    )


async def _mutate(
    session_id: str, message_id: str, owner_id: str, change: Callable[[Any, Any, dict], T]
) -> T:
    try:
        with session_write_lease(session_id):
            return await _cas(session_id, message_id, owner_id, change)
    except SessionBusyError as exc:
        raise HTTPException(
            409, "Wait for the current turn before preparing its illustration."
        ) from exc


async def _cas(
    session_id: str, message_id: str, owner_id: str, change: Callable[[Any, Any, dict], T]
) -> T:
    for _attempt in range(3):
        async with database.AsyncSessionLocal() as db:
            state, message = await owned_context(db, session_id, message_id, owner_id)
            snapshot = require_snapshot(state, message)
            before = deepcopy(state.entity_states or {})
            result = change(state, message, snapshot)
            after = deepcopy(state.entity_states or {})
            if before == after:
                return result
            # Do not autoflush an ORM JSON assignment ahead of the CAS.
            db.expunge(state)
            changed = await db.execute(
                update(SessionState)
                .where(
                    SessionState.session_id == session_id,
                    SessionState.entity_states == before,
                )
                .values(entity_states=after)
            )
            if cast(CursorResult, changed).rowcount == 1:
                await db.commit()
                return result
            await db.rollback()
    raise HTTPException(409, "The session changed while saving the visual plan. Try again.")


async def begin(
    session_id: str,
    message_id: str,
    owner_id: str,
    expected: dict,
    profile_key: str,
    refresh: bool = False,
) -> tuple[str, str, dict | None]:
    def prepare(state: Any, message: Any, snapshot: dict) -> tuple[str, str, dict | None]:
        keys = ("nonce", "content_hash", "visible_facts", "source_revision_id")
        if fingerprint({k: snapshot.get(k) for k in keys}) != fingerprint(
            {k: expected.get(k) for k in keys}
        ):
            raise HTTPException(409, "The saved scene changed before plan preparation.")
        if read_settings(state).visual_preparation != "plan":
            raise HTTPException(409, "Visual plan preparation was disabled.")
        if expected.get("preferences") != read_settings(state).model_dump():
            raise HTTPException(409, "Visual preferences changed before plan preparation.")
        states = deepcopy(state.entity_states or {})
        if not isinstance(states.get(KEY), dict) or refresh:
            states = reset(states)
        state.entity_states = states
        identity = token(state, message, snapshot)
        key = fingerprint([identity, profile_key])
        entry = states[KEY].get("entries", {}).get(key)
        return identity, key, deepcopy(entry)

    return await _mutate(session_id, message_id, owner_id, prepare)


async def publish(
    session_id: str, message_id: str, owner_id: str, identity: str, key: str, entry: dict
) -> dict:
    def write(state: Any, message: Any, snapshot: dict) -> dict:
        if token(state, message, snapshot) != identity:
            raise HTTPException(
                409, "The scene or its settings changed. The late visual plan was discarded."
            )
        states = deepcopy(state.entity_states or {})
        cache = states[KEY]
        existing = cache.get("entries", {}).get(key)
        if existing is not None:
            return deepcopy(existing)  # The first committed immutable artifact wins.
        entries = {**cache.get("entries", {}), key: entry}
        while len(entries) > MAX_ENTRIES or len(json.dumps(entries).encode()) > MAX_BYTES:
            if len(entries) == 1:
                raise ValueError("The prepared visual plan exceeds the cache size limit.")
            entries.pop(next(iter(entries)))
        cache["entries"] = entries
        state.entity_states = states
        return entry

    return await _mutate(session_id, message_id, owner_id, write)


async def verify(session_id: str, message_id: str, owner_id: str, identity: str) -> None:
    def check(state: Any, message: Any, snapshot: dict) -> None:
        if token(state, message, snapshot) != identity:
            raise HTTPException(409, "The scene changed after its visual plan was prepared.")

    await _mutate(session_id, message_id, owner_id, check)
