"""Canonical item transfers for actor commands without fabricated narration evidence."""

from collections.abc import Iterable
from copy import deepcopy
from typing import Literal

from backend.engine.clothing.profiles import potentially_wearable
from backend.engine.clothing.projection import item_wear_state
from backend.engine.narrated_items.actor_items import receive as _receive
from backend.engine.narrated_items.actor_items import remove as _remove
from backend.engine.narrated_items.errors import ItemTransferError
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
        raise ItemTransferError("recipient_unavailable")
    return str(recipient)


def carried_after(actor_id: str, receipts: Iterable[dict]) -> frozenset[str]:
    """Read ordered host receipts; this transient proof never assesses unknown other clothing."""
    carried: set[str] = set()
    for receipt in receipts:
        identifier = receipt.get("item_id")
        if not isinstance(identifier, str):
            continue
        if "destination_owner" in receipt:
            carried.discard(identifier)
            if receipt["destination_owner"] == actor_id and receipt.get("disposition") == "carried":
                carried.add(identifier)
        elif receipt.get("operation") in {"wear", "adjust", "remove"}:
            carried.discard(identifier)
            if receipt["operation"] == "remove":
                carried.add(identifier)
    return frozenset(carried)


def _require_carried(
    owner: dict, item: dict, item_id: str, carried_item_ids: frozenset[str]
) -> None:
    status = item_wear_state(
        owner["visual_profile"], owner["resolved_inventory"], item_id, equipment=owner["equipment"]
    )
    if status == "unknown" and potentially_wearable(item) and item_id not in carried_item_ids:
        raise ItemTransferError("unknown_wear_state")
    if status == "worn":
        raise ItemTransferError("item_worn")


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
    carried_item_ids: frozenset[str] = frozenset(),
) -> tuple[dict, Possessions, dict]:
    """Validate against present custody, then change working copies through item owners."""
    if operation not in {"take", "give", "put_down"} or actor_id not in actors:
        raise ItemTransferError("operation_unavailable")
    source = SCENE if operation == "take" else actor_id
    if item_id not in snapshot.items or snapshot.owners.get(item_id) != source:
        raise ItemTransferError("custody_changed")
    destination = _destination(actor_id, operation, recipient_id, actors)
    if source != SCENE:
        _require_carried(actors[source], snapshot.items[item_id], item_id, carried_item_ids)
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
