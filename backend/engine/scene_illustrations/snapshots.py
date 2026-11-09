"""Bounded, message-time visual facts, independent of current game state."""

import hashlib
from copy import deepcopy
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.engine.visual_plan_lifecycle import prune, without_cache
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
    result: dict[str, Any] = {
        key: str(facts[key])[:2000]
        for key in ("setting", "lighting", "visible_action", "staging_status")
        if facts.get(key)
    }
    result["props"] = [
        {
            key: str(item[key])[: 1000 if key == "description" else 200]
            for key in ("item_id", "owner_id", "name", "spatial_position", "description")
            if key in item
        }
        for item in (facts.get("props") or [])[:24]
        if isinstance(item, dict)
    ]
    result["explicit"] = [
        {
            "category": str(atom["category"])[:40],
            "participants": [
                str(pid)[:100] for pid in atom["participants"][:6] if str(pid).strip()
            ],
            "evidence": str(atom.get("evidence") or "")[:800],
        }
        for atom in (facts.get("explicit") or [])[:8]
        if isinstance(atom, dict)
        and atom.get("category")
        and isinstance(atom.get("participants"), list)
        and atom["participants"]
    ]
    people = facts.get("characters") or []
    result["characters"] = [
        {
            **(
                {
                    "placement": {
                        key: str(person["placement"][key])[:120]
                        for key in ("relation", "target_kind", "target")
                        if key in person["placement"]
                    }
                }
                if isinstance(person.get("placement"), dict)
                else {}
            ),
            **(
                {"clothing_tokens": [str(token)[:200] for token in person["clothing_tokens"][:32]]}
                if isinstance(person.get("clothing_tokens"), list)
                else {}
            ),
            **({"managed_clothing": True} if person.get("managed_clothing") is True else {}),
            **(
                {"clothing_detail_limited": True}
                if person.get("clothing_detail_limited") is True
                else {}
            ),
            **{
                key: str(person[key])[:1000]
                for key in ("id", "name", "appearance", "clothing", "position", "posture")
                if person.get(key)
            },
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
        "source_message_id": message.id,
        "source_revision_id": message.revision_id,
        "content_hash": content_hash(message),
        "scene_id": message.scene_id,
        "sequence_id": message.sequence_id,
        "narration": message.content[-MAX_NARRATION:],
        "visible_facts": _visible_facts(public_visual_facts),
    }
    registry["snapshots"] = dict(list(registry["snapshots"].items())[-MAX_SNAPSHOTS:])
    states[REGISTRY_KEY] = registry
    prune(states, set(registry["snapshots"]))
    state.entity_states = states


def remap_illustrations(entity_states: dict | None, message_id_map: dict[str, str]) -> dict:
    """Copy/import exact message references, without replacing text or asset URLs."""
    states = without_cache(entity_states)
    if REGISTRY_KEY not in states:
        return states
    registry = registry_of(states)
    for kind in ("snapshots", "images"):
        registry[kind] = {
            message_id_map[key]: value
            for key, value in registry[kind].items()
            if key in message_id_map and isinstance(value, dict)
        }
    for message_id, snapshot in registry["snapshots"].items():
        snapshot["nonce"] = uuid4().hex
        if "source_message_id" in snapshot:
            snapshot["source_message_id"] = message_id
    states[REGISTRY_KEY] = registry
    return states
