"""Canonical item transfers for actor commands without fabricated narration evidence."""

from copy import deepcopy
from typing import Literal

from backend.engine.clothing.projection import known_worn_item_ids
from backend.engine.narrated_items.apply import _receive, _remove
from backend.engine.visual_novel.continuity import PLAYER, SCENE, Possessions

Operation = Literal["take", "give", "put_down"]


def _destination(
    actor_id: str, operation: Operation, recipient_id: str | None, actors: dict
) -> str:
    if operation == "take":
        return actor_id
    if operation == "put_down":
        return SCENE
    recipient = PLAYER if recipient_id == "@player" else recipient_id
    if recipient not in actors or recipient == actor_id:
        raise ValueError("The recipient is unavailable or already owns this item.")
    return str(recipient)


def transfer(
    actors: dict,
    snapshot: Possessions,
    actor_id: str,
    item_id: str,
    operation: Operation,
    *,
    detailed: bool,
    recipient_id: str | None = None,
    position: str | None = None,
) -> tuple[dict, Possessions, dict]:
    """Validate against present custody, then change working copies through item owners."""
    if operation not in {"take", "give", "put_down"} or actor_id not in actors:
        raise ValueError("The item operation or actor is unavailable.")
    source = SCENE if operation == "take" else actor_id
    if item_id not in snapshot.items or snapshot.owners.get(item_id) != source:
        raise ValueError("The item is unavailable for this transfer under its current custody.")
    destination = _destination(actor_id, operation, recipient_id, actors)
    if source != SCENE:
        owner = actors[source]
        worn = known_worn_item_ids(
            owner["visual_profile"], owner["resolved_inventory"], equipment=owner["equipment"]
        )
        if worn and item_id in worn:
            raise ValueError("This item is worn; take it off before transferring it.")
    changed = deepcopy(actors)
    after = deepcopy(snapshot)
    item = deepcopy(snapshot.items[item_id])
    physical_position = position if operation == "put_down" else None
    if physical_position is not None or "spatial_position" in item:
        item["spatial_position"] = physical_position
    if source != SCENE:
        _remove(changed[source], item_id)
    if destination != SCENE:
        _receive(changed[destination], item, "carried", detailed)
    after.items[item_id] = item
    after.owners[item_id] = destination
    for key in after.npcs:
        if key in changed:
            after.npcs[key]["inventory"] = deepcopy(changed[key]["resolved_inventory"])
    return (
        changed,
        after,
        {
            "item": item,
            "source_owner": source,
            "destination_owner": destination,
            "disposition": "carried",
            "spatial_position": physical_position,
        },
    )
