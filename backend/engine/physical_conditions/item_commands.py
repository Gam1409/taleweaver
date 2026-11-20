"""Apply an actor's validated item-property command through existing ledger primitives."""

from copy import deepcopy

from backend.engine.clothing.schema import VisualProfile, WornItem
from backend.engine.physical_conditions.command_source import CommandProof
from backend.engine.physical_conditions.ledger import _record, _retain, _update, read
from backend.engine.physical_conditions.schema import KEY, ConditionProposal, Event, Ledger, Source
from backend.engine.rule_engine import InventoryItem, WorldEntityUpdate

_OWNER_FIELDS = (
    set(InventoryItem.model_fields)
    | set(WorldEntityUpdate.model_fields)
    | set(WornItem.model_fields)
    | set(VisualProfile.model_fields)
    | {
        "owner_id",
        "worn_by",
        "property_owner_id",
        "current_scene_id",
        "visual_profile",
        "equipment",
        "posture",
        "placement",
        "emotion",
    }
)


def _previous(
    ledger: Ledger,
    proof: CommandProof,
    request_hash: str,
    message_id: str,
    item_id: str,
    dimension: str,
    detail: str,
) -> str | None:
    matches = [
        event
        for event in ledger.events
        if event.source.command and event.source.command.id == proof.id
    ]
    if not matches:
        return None
    event = matches[-1]
    condition = ledger.conditions.get(event.condition_id)
    if (
        event.source.command != proof
        or event.source.content_hash != request_hash
        or event.source.message_id != message_id
        or condition is None
        or condition.target_id != item_id
        or condition.part.casefold() != dimension.casefold()
        or event.detail != detail
    ):
        raise ValueError("An operation identity cannot be reused for a different request.")
    return event.condition_id


def apply_command(
    states: dict,
    *,
    item_id: str,
    dimension: str,
    detail: str,
    owned_item_ids: set[str],
    proof: CommandProof,
    message_id: str,
    request_hash: str,
    session_id: str,
    minute: int,
    visibility: str = "public",
) -> tuple[dict, str]:
    """Copy-on-write facts; the caller supplies freshly checked custody and source scope."""
    if item_id not in owned_item_ids:
        raise ValueError("The command actor must own the item.")
    if dimension.casefold() in _OWNER_FIELDS:
        raise ValueError("Item identity and mechanical attributes have separate owners.")
    ledger = read(states).model_copy(deep=True)
    previous = _previous(ledger, proof, request_hash, message_id, item_id, dimension, detail)
    if previous is not None:
        return deepcopy(states), previous
    active = [
        row
        for row in ledger.conditions.values()
        if row.target_id == item_id
        and row.kind == "item_state"
        and row.part.casefold() == dimension.casefold()
        and row.status != "resolved"
    ]
    if len(active) > 1:
        raise ValueError("Ambiguous existing item properties were preserved.")
    proposal = ConditionProposal.model_validate(
        {
            "operation": "change" if active else "record",
            **(
                {"condition_id": active[0].id}
                if active
                else {"target_id": item_id, "kind": "item_state", "part": dimension}
            ),
            "detail": detail,
            "visibility": visibility,
            "evidence": "Item property command: " + detail,
        }
    )
    source = Source(
        kind="command",
        message_id=message_id,
        content_hash=request_hash,
        quote=detail,
        command=proof,
    )
    condition = (
        _update(ledger, proposal, source, owned_item_ids, minute)
        if active
        else _record(ledger, proposal, source, owned_item_ids, session_id, 0, proof.id, minute)
    )
    ledger.conditions[condition.id] = condition
    ledger.revision += 1
    ledger.events.append(
        Event(
            condition_id=condition.id,
            operation=proposal.operation,
            revision=ledger.revision,
            source=source,
            detail=detail,
            minute=minute,
        )
    )
    _retain(ledger)
    ledger.last_check = {
        "message_id": message_id,
        "command_id": proof.id,
        "status": "complete",
        "accepted": [condition.id],
        "rejected": [],
        "minute": minute,
        "proposed_count": 1,
    }
    changed = deepcopy(states)
    changed[KEY] = Ledger.model_validate(ledger.model_dump()).model_dump()
    return changed, condition.id
