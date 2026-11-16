"""Bind repeated automatic observations to one exact canonical physical condition."""

from typing import Any

from pydantic import ValidationError

from backend.engine.physical_conditions.schema import MAX_PROPOSALS, ConditionProposal, Ledger


def bind_records(ledger: Ledger, proposals: list[Any]) -> tuple[list[Any], list[dict]]:
    """Resolve identity only; the ledger still validates evidence, scope and transitions."""
    if len(proposals) > MAX_PROPOSALS:
        return proposals, []
    active: dict[tuple, list[str]] = {}
    for row in ledger.conditions.values():
        if row.status != "resolved":
            active.setdefault((row.target_id, row.kind, row.part.casefold()), []).append(row.id)
    bound, audit = [], []
    for index, raw in enumerate(proposals):
        proposal = _bind(raw, active)
        bound.append(proposal if proposal is not None else raw)
        if proposal is not None:
            audit.append({"proposal": index + 1, "condition_id": proposal["condition_id"]})
    return bound, audit


def _bind(raw: Any, active: dict[tuple, list[str]]) -> dict | None:
    try:
        proposal = ConditionProposal.model_validate(raw)
    except ValidationError:
        return None
    if proposal.operation != "record":
        return None
    matches = active.get((proposal.target_id, proposal.kind, proposal.part.casefold()), [])
    if len(matches) != 1:
        return None
    return ConditionProposal.model_validate(
        {
            **proposal.model_dump(),
            "operation": "change",
            "condition_id": matches[0],
            "target_id": None,
            "kind": None,
            "part": "",
        }
    ).model_dump()
