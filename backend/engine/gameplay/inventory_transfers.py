"""Canonical item hydration and successful possession transfers shared by turn paths."""

from copy import deepcopy
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified

from backend.core.state_rejection_trace import reject
from backend.engine.gameplay.turn_context import TurnContext
from backend.engine.visual_novel.continuity import (
    PLAYER,
    CanonicalInventoryItem,
    possession_snapshot,
)
from backend.engine.visual_novel.ownership import materialize_scene_possession
from backend.models.world_entity import WorldEntity


def _rejected_drop(
    context: TurnContext, item: dict[str, Any], reason: str, actual: dict[str, Any]
) -> bool:
    reject(
        "inventory",
        f"inventory.drop_{reason}_invalid",
        "The existing possession did not transfer to the current scene.",
        proposal=item,
        source={"owner": PLAYER, "session_id": context.game_id},
        expected={
            "item_id": item.get("id") or "nonempty canonical possession ID",
            "current_scene_id": context.state.current_scene_id,
            "is_in_inventory": False,
            "is_hidden": False,
        },
        actual=actual,
    )
    return False


def clear_dropped_references(context: TurnContext, identifier: str) -> None:
    """Clear only the transferred item's legacy equipment and canonical worn references."""
    context.avatar.equipment = {
        slot: None
        if (entry.get("id") if isinstance(entry, dict) else entry) == identifier
        else entry
        for slot, entry in (context.avatar.equipment or {}).items()
    }
    profile = context.avatar.visual_profile
    if not isinstance(profile, dict) or not isinstance(profile.get("worn"), list):
        return
    kept = [
        entry
        for entry in profile["worn"]
        if not isinstance(entry, dict) or entry.get("item_id") != identifier
    ]
    if kept != profile["worn"]:
        context.avatar.visual_profile = {**deepcopy(profile), "worn": deepcopy(kept)}


async def available_inventory_sources(
    context: TurnContext, identifiers: set[str]
) -> dict[str, dict]:
    """Session rows shadow legacy blueprint rows; only accessible possessions can transfer."""
    if not identifiers:
        return {}
    rows = list(
        await context.db.scalars(
            select(WorldEntity).where(WorldEntity.session_id == context.game_id)
        )
    )
    missing = identifiers - {row.id for row in rows}
    if missing and context.state.template_id:
        rows.extend(
            await context.db.scalars(
                select(WorldEntity).where(
                    WorldEntity.template_id == context.state.template_id,
                    WorldEntity.session_id.is_(None),
                    WorldEntity.id.in_(missing),
                )
            )
        )
    snapshot = possession_snapshot(context.manager, rows)
    return {
        identifier: snapshot.items[identifier]
        for identifier in identifiers
        if identifier in snapshot.items and snapshot.owners[identifier] != PLAYER
    }


async def transfer_possession_to_scene(context: TurnContext, item: dict[str, Any]) -> bool:
    """Create a row for an existing possession, or confirm its exact existing row moved."""
    identifier = item.get("id")
    if not isinstance(identifier, str) or not identifier:
        return _rejected_drop(context, item, "identity", {"item_id": identifier})
    row = await context.db.scalar(
        select(WorldEntity).where(
            WorldEntity.session_id == context.game_id,
            WorldEntity.entity_type == "OBJECT",
            WorldEntity.id == identifier,
        )
    )
    if row is None:
        row = materialize_scene_possession(
            context.db, context.state, CanonicalInventoryItem.model_validate(deepcopy(item))
        )
        await context.db.flush()
    else:
        await context._spawn_scene_item(item)
    if (
        row.current_scene_id != context.state.current_scene_id
        or row.is_in_inventory
        or row.is_hidden
    ):
        return _rejected_drop(
            context,
            item,
            "destination",
            {
                "item_id": row.id,
                "current_scene_id": row.current_scene_id,
                "is_in_inventory": row.is_in_inventory,
                "is_hidden": row.is_hidden,
            },
        )
    states = dict(context.state.entity_states or {})
    states[identifier] = {
        **states.get(identifier, {}),
        "is_in_inventory": False,
        "is_hidden": False,
        "current_scene_id": context.state.current_scene_id,
        "vn_item_data": deepcopy(item),
    }
    context.state.entity_states = states
    flag_modified(context.state, "entity_states")
    return True
