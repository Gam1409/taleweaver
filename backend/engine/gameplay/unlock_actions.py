"""Shared deterministic unlock actions, with no HTTP route dependency."""

from typing import Any

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from backend.engine.gameplay.session_access import _require_session_state
from backend.engine.gameplay.unlock_service import (
    add_system_message,
    avatar_has_item,
    award_session_unlock_xp,
    enforce_container_guard,
    enforce_exit_guard,
    fire_container_unlock_success,
    inventory_item_name,
    load_avatar,
    load_session_object,
    mark_container_unlocked,
    open_exit,
    require_avatar,
    require_value,
)
from backend.engine.gameplay.unlock_targets import _require_session_exit, _resolve_session_exit
from backend.models.user import User
from backend.schemas.unlock_actions import (
    ContainerUnlockCodeRequest,
    ContainerUnlockItemRequest,
    ExitUnlockCodeRequest,
    ExitUnlockItemRequest,
)

INVALID_CONTAINER_CODE_MESSAGE = (
    "The lock gives a mocking click. That code won't open this container."
)
INVALID_EXIT_CODE_MESSAGE = "That code does not open this way."


async def unlock_container_with_code(
    game_id: str,
    entity_id: str,
    payload: ContainerUnlockCodeRequest,
    db: AsyncSession,
    current_user: User,
) -> dict[str, Any]:
    """Deterministically unlocks a container when the provided code matches code_to_unlock."""
    state = await _require_session_state(db, game_id, current_user)
    entity = await load_session_object(db, state, entity_id, "CONTAINER", "Container not found.")
    metadata_json = dict(entity.metadata_json or {})
    expected_code = require_value(
        metadata_json.get("code_to_unlock"), "This container does not require a code."
    )
    submitted_code = require_value(payload.code, "Code is required.")
    if submitted_code.lower() != expected_code.lower():
        raise HTTPException(status_code=403, detail=INVALID_CONTAINER_CODE_MESSAGE)

    await enforce_container_guard(db, state, entity, metadata_json)

    # Only the first unlock grants XP.
    if mark_container_unlocked(state, entity.id):
        avatar = await load_avatar(db, state)
        if avatar:
            xp_reward = await award_session_unlock_xp(db, state, avatar, metadata_json)
            add_system_message(db, state, f"Unlocked {entity.name} with the correct code!")
            if xp_reward:
                add_system_message(db, state, f"you gained {xp_reward} XP")
        await fire_container_unlock_success(db, state, entity, metadata_json)

    await db.commit()
    return {"status": "ok", "entity_id": entity.id, "locked": False}


async def unlock_container_with_item(
    game_id: str,
    entity_id: str,
    payload: ContainerUnlockItemRequest,
    db: AsyncSession,
    current_user: User,
) -> dict[str, Any]:
    """Deterministically unlocks a container when the player possesses the required item."""
    state = await _require_session_state(db, game_id, current_user)
    entity = await load_session_object(db, state, entity_id, "CONTAINER", "Container not found.")
    metadata_json = dict(entity.metadata_json or {})
    expected_item_id = require_value(
        metadata_json.get("item_to_unlock"), "This container does not require an item to unlock."
    ).upper()
    submitted_item_id = require_value(payload.item_id, "Item ID is required.").upper()
    if submitted_item_id != expected_item_id:
        raise HTTPException(status_code=403, detail="This item cannot unlock this container.")

    avatar = await require_avatar(db, state)
    if not avatar_has_item(avatar, submitted_item_id):
        raise HTTPException(status_code=403, detail="You do not possess the required key item.")

    await enforce_container_guard(db, state, entity, metadata_json)

    # Only the first unlock grants XP.
    if mark_container_unlocked(state, entity.id):
        xp_reward = await award_session_unlock_xp(db, state, avatar, metadata_json)
        item_name = inventory_item_name(avatar, submitted_item_id)
        add_system_message(db, state, f"Unlocked {entity.name} using {item_name}!")
        if xp_reward:
            add_system_message(db, state, f"you gained {xp_reward} XP")
        await fire_container_unlock_success(db, state, entity, metadata_json)

    await db.commit()
    return {"status": "ok", "entity_id": entity.id, "locked": False}


async def unlock_container(
    game_id: str,
    entity_id: str,
    db: AsyncSession,
    current_user: User,
) -> dict[str, Any]:
    """Deterministically unlocks a container directly (evaluating unlock_expression if present)."""
    state = await _require_session_state(db, game_id, current_user)
    entity = await load_session_object(db, state, entity_id, "CONTAINER", "Container not found.")
    metadata_json = dict(entity.metadata_json or {})
    if metadata_json.get("code_to_unlock"):
        raise HTTPException(status_code=400, detail="This container requires a passcode.")
    if metadata_json.get("item_to_unlock"):
        raise HTTPException(status_code=400, detail="This container requires a key item.")

    await enforce_container_guard(db, state, entity, metadata_json)

    # Only the first unlock grants XP.
    if mark_container_unlocked(state, entity.id):
        avatar = await load_avatar(db, state)
        if avatar:
            await award_session_unlock_xp(db, state, avatar, metadata_json)
            add_system_message(db, state, f"Unlocked {entity.name}!")
        await fire_container_unlock_success(db, state, entity, metadata_json)

    await db.commit()
    return {"status": "ok", "entity_id": entity.id, "locked": False}


async def unlock_exit_with_code(
    game_id: str,
    exit_id: str,
    payload: ExitUnlockCodeRequest,
    db: AsyncSession,
    current_user: User,
) -> dict[str, Any]:
    """Unlocks an exit by validating a submitted access code."""
    state = await _require_session_state(db, game_id, current_user)
    world_exit = await _require_session_exit(db, state, exit_id)
    expected = require_value(world_exit.code_to_unlock, "This exit does not require a code.")
    submitted = require_value(payload.code, "Code is required.")
    if submitted.lower() != expected.lower():
        raise HTTPException(status_code=403, detail=INVALID_EXIT_CODE_MESSAGE)

    await enforce_exit_guard(db, state, world_exit)
    return await open_exit(
        db,
        state,
        world_exit,
        f"{world_exit.label or 'The exit'} accepts the code and the way is open.",
    )


async def unlock_exit_with_item(
    game_id: str,
    exit_id: str,
    payload: ExitUnlockItemRequest,
    db: AsyncSession,
    current_user: User,
) -> dict[str, Any]:
    """Unlocks an exit when the player possesses the required key item."""
    state = await _require_session_state(db, game_id, current_user)
    world_exit = await _require_session_exit(db, state, exit_id)
    expected_item = require_value(
        world_exit.item_to_unlock, "This exit does not require an item to unlock."
    ).upper()
    submitted_item = require_value(payload.item_id, "Item ID is required.").upper()
    if submitted_item != expected_item:
        raise HTTPException(status_code=403, detail="This item cannot unlock this exit.")

    avatar = await require_avatar(db, state)
    if not avatar_has_item(avatar, submitted_item):
        raise HTTPException(status_code=403, detail="You do not possess the required key item.")
    item_name = inventory_item_name(avatar, submitted_item)

    await enforce_exit_guard(db, state, world_exit)
    return await open_exit(
        db,
        state,
        world_exit,
        f"{world_exit.label or 'The exit'} yields to {item_name} and the way is open.",
    )


async def unlock_exit(
    game_id: str,
    exit_id: str,
    db: AsyncSession,
    current_user: User,
) -> dict[str, Any]:
    """Deterministically unlocks an exit directly (evaluating unlock_expression if present)."""
    state = await _require_session_state(db, game_id, current_user)
    world_exit = await _require_session_exit(db, state, exit_id)
    if world_exit.code_to_unlock:
        raise HTTPException(status_code=400, detail="This exit requires a passcode.")
    if world_exit.item_to_unlock:
        raise HTTPException(status_code=400, detail="This exit requires a key item.")

    await enforce_exit_guard(db, state, world_exit)
    return await open_exit(
        db, state, world_exit, f"{world_exit.label or 'The exit'} unlocks and the way is open."
    )


__all__ = [
    "_resolve_session_exit",
    "unlock_container",
    "unlock_container_with_code",
    "unlock_container_with_item",
    "unlock_exit",
    "unlock_exit_with_code",
    "unlock_exit_with_item",
]
