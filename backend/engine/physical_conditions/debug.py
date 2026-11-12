"""Owned-session debug view and explicit manual corrections; no model call."""

import json
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.engine.clothing.profiles import owned_items
from backend.engine.physical_conditions.ledger import apply, read
from backend.models.avatar import Avatar
from backend.models.session_state import SessionState
from backend.models.world_entity import WorldEntity


def view(state: Any, npcs: list[dict], items: list[dict], avatar: Any) -> dict:
    subjects = {
        "__player__": {"id": "__player__", "name": getattr(avatar, "name", "Player") or "Player"}
    }
    equipped = owned_items([], equipment=getattr(avatar, "equipment", None))
    for row in [*equipped.values(), *npcs, *items]:
        identifier = row.get("id")
        if isinstance(identifier, str):
            subjects[identifier] = {"id": identifier, "name": row.get("name") or identifier}
    try:
        ledger = read(state.entity_states)
    except ValueError as exc:
        return {"error": str(exc), "subjects": list(subjects.values())}
    return {**ledger.model_dump(), "subjects": list(subjects.values())}


async def _targets(db: AsyncSession, state: SessionState, avatar: Any) -> tuple[set[str], set[str]]:
    if avatar is None:
        avatar = await db.get(Avatar, state.avatar_id)
    item_targets = set(owned_items([], equipment=getattr(avatar, "equipment", None)))
    targets = {"__player__", *item_targets}
    inventories = [getattr(avatar, "inventory", []) or []]
    entities = await db.scalars(
        select(WorldEntity).where(WorldEntity.session_id == state.session_id)
    )
    for actor in entities:
        targets.add(actor.id)
        if actor.entity_type == "OBJECT":
            item_targets.add(actor.id)
        override = (state.entity_states or {}).get(actor.id) or {}
        inventories.append(
            override.get(
                "inventory", actor.inventory or (actor.metadata_json or {}).get("inventory") or []
            )
        )
    for inventory in inventories:
        for item in inventory if isinstance(inventory, list) else []:
            identifier = item.get("id") if isinstance(item, dict) else item
            if isinstance(identifier, str):
                targets.add(identifier)
                item_targets.add(identifier)
    return targets, item_targets


async def command(
    db: AsyncSession,
    state: SessionState,
    args: str,
    user: Any = None,
    adventure: Any = None,
    avatar: Any = None,
) -> str:
    if not state.is_debug_enabled:
        return "DEBUG ERROR: Enable debug mode first."
    try:
        raw = json.loads(args.split(" ", 1)[1])
        if not isinstance(raw, dict):
            raise ValueError("Expected an operation object.")
        expected = raw.pop("expected_revision", None)
        ledger = read(state.entity_states)
        if type(expected) is not int or expected != ledger.revision:
            return "DEBUG ERROR: Physical condition state changed. Refresh before editing."
        raw.setdefault("evidence", "Explicit manual debug correction.")
        targets, item_targets = await _targets(db, state, avatar)
        existing = ledger.conditions.get(raw.get("condition_id") or "")
        if existing:
            targets.add(
                existing.target_id
            )  # Allows resolving a retained record for a removed subject.
        states, accepted, rejected = apply(
            state.entity_states,
            [raw],
            targets=targets,
            narration="",
            message_id="manual:" + str(uuid4()),
            session_id=state.session_id,
            minute=int(state.in_game_time or 0),
            manual=True,
            item_targets=item_targets,
        )
    except (ValueError, TypeError, IndexError):
        return "DEBUG ERROR: Invalid condition command; no physical state was changed."
    if rejected:
        return "DEBUG ERROR: " + " ".join(rejected)
    state.entity_states = states
    return f"DEBUG: Updated {len(accepted)} physical condition. No time, inventory or NPC personality changes."
