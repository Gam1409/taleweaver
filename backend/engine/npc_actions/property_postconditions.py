"""Inspect item-property owner facts and their command provenance, never preview copies."""

from hashlib import sha256
from typing import TYPE_CHECKING, Any

from backend.engine import turn_controls
from backend.engine.npc_actions.contracts import ChangeState, Use
from backend.engine.npc_actions.property_values import requested_property
from backend.engine.physical_conditions.ledger import read
from backend.engine.physical_conditions.schema import Condition, Ledger

if TYPE_CHECKING:
    from backend.engine.npc_actions.preview import Scope


def _source(
    row: Condition,
    ledger: Ledger,
    scope: "Scope",
    request: ChangeState | Use,
    operation: turn_controls.Operation,
) -> bool:
    source, proof = row.latest, row.latest.command
    if (
        source.kind != "command"
        or proof is None
        or (proof.id, proof.actor_id, proof.operation)
        != (operation.command_id, scope.actor_id, request.tool)
        or source.message_id != scope.input_id
        or source.content_hash != sha256(request.model_dump_json().encode()).hexdigest()
        or source.quote != row.detail
        or source.evidence_span is not None
    ):
        return False
    return any(
        event.condition_id == row.id
        and event.source == source
        and event.detail == row.detail
        and event.revision == row.updated_revision
        and event.operation in {"record", "change"}
        for event in ledger.events
    )


def verify(
    manager: Any,
    scope: "Scope",
    request: ChangeState | Use,
    effect: dict,
    operation: turn_controls.Operation,
) -> str | None:
    try:
        ledger = read(manager.state.entity_states)
    except ValueError:
        return "property_storage"
    dimension, detail, visibility = requested_property(request)
    row = ledger.conditions.get(effect.get("condition_id", ""))
    matches = [
        value
        for value in ledger.conditions.values()
        if value.target_id == request.item_id
        and value.kind == "item_state"
        and value.part == dimension
        and value.status == "active"
    ]
    if (
        row is None
        or len(matches) != 1
        or matches[0].id != row.id
        or effect.get("item_id") != request.item_id
        or effect.get("dimension") != dimension
    ):
        return "property_identity"
    if row.detail != detail or effect.get("detail") != detail:
        return "property_value"
    if row.visibility != visibility or row.visual_detail or row.visual_region is not None:
        return "property_visibility"
    return None if _source(row, ledger, scope, request, operation) else "property_source"
