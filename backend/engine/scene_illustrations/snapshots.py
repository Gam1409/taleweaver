"""Bounded, message-time visual facts, independent of current game state."""

import hashlib
from copy import deepcopy
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.chat import ChatMessage
from backend.models.session_state import SessionState

REGISTRY_KEY = "__vn_illustrations__"
MAX_SNAPSHOTS = 100
MAX_NARRATION = 16000


def content_hash(message: ChatMessage) -> str:
    source = "\0".join(
        str(value or "") for value in (message.content, message.scene_id, message.sequence_id)
    )
    return hashlib.sha256(source.encode()).hexdigest()


def registry_of(entity_states: dict | None) -> dict:
    value = (entity_states or {}).get(REGISTRY_KEY)
    if not isinstance(value, dict):
        return {"version": 1, "snapshots": {}, "images": {}}
    return {
        "version": 1,
        "snapshots": deepcopy(value.get("snapshots") or {}),
        "images": deepcopy(value.get("images") or {}),
    }


def _visible_facts(value: dict | None) -> dict:
    """Accept only caller-selected public appearance facts; never copy inventory/goals."""
    facts = value or {}
    result = {
        key: str(facts[key])[:2000]
        for key in ("setting", "lighting", "visible_action")
        if facts.get(key)
    }
    people = facts.get("characters") or []
    result["characters"] = [
        {
            key: str(person[key])[:1000]
            for key in ("id", "name", "appearance", "clothing", "position")
            if person.get(key)
        }
        for person in people[:12]
        if isinstance(person, dict)
    ]
    return result


async def capture_scene_snapshot(
    db: AsyncSession,
    state: SessionState,
    message: ChatMessage,
    public_visual_facts: dict[str, Any] | None = None,
) -> None:
    """Called only for completed VN narration, after flush and before the turn commit.

    The caller must supply only visible, present characters and public appearance.
    Missing appearance stays unspecified; it is never filled from a later turn.
    """
    if message.role != "assistant" or not message.id or message.session_id != state.session_id:
        return
    if not (message.content or "").strip():
        return
    states = deepcopy(state.entity_states or {})
    registry = registry_of(states)
    # Preserve image jobs completed while this turn was using an older state object.
    with db.no_autoflush:
        persisted = await db.scalar(
            select(SessionState.entity_states).where(SessionState.id == state.id)
        )
    saved_images = registry_of(persisted)["images"]
    registry["images"] = {**registry["images"], **saved_images}
    registry["snapshots"][message.id] = {
        "nonce": uuid4().hex,
        "content_hash": content_hash(message),
        "scene_id": message.scene_id,
        "sequence_id": message.sequence_id,
        "narration": message.content[:MAX_NARRATION],
        "visible_facts": _visible_facts(public_visual_facts),
    }
    registry["snapshots"] = dict(list(registry["snapshots"].items())[-MAX_SNAPSHOTS:])
    states[REGISTRY_KEY] = registry
    state.entity_states = states


def remap_illustrations(entity_states: dict | None, message_id_map: dict[str, str]) -> dict:
    """Copy/import exact message references, without replacing text or asset URLs."""
    states = deepcopy(entity_states or {})
    if REGISTRY_KEY not in states:
        return states
    registry = registry_of(states)
    for kind in ("snapshots", "images"):
        registry[kind] = {
            message_id_map[key]: value
            for key, value in registry[kind].items()
            if key in message_id_map and isinstance(value, dict)
        }
    for snapshot in registry["snapshots"].values():
        snapshot["nonce"] = uuid4().hex
    states[REGISTRY_KEY] = registry
    return states
