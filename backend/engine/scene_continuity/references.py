"""Resolve repeated observations by exact current-scene identity, never prose similarity."""

from typing import Any

from pydantic import ValidationError

from .schema import MAX_UPDATES, Ledger, Update


def bind_records(
    ledger: Ledger, proposals: list[Any], scene_id: str
) -> tuple[list[Any], list[dict]]:
    """Only identify a unique non-ended record; all existing validators still run."""
    if len(proposals) > MAX_UPDATES:
        return proposals, []
    known: dict[tuple, list[str]] = {}
    for row in ledger.records.values():
        if row.scene_id == scene_id and row.status != "ended":
            known.setdefault((row.subject_id, row.kind, row.key), []).append(row.id)
    result, bindings = [], []
    for index, raw in enumerate(proposals):
        bound = _bind(raw, known)
        result.append(bound if bound is not None else raw)
        if bound is not None:
            bindings.append({"proposal": index + 1, "record_id": bound["record_id"]})
    return result, bindings


def _bind(raw: Any, known: dict[tuple, list[str]]) -> dict | None:
    try:
        proposal = Update.model_validate(raw)
    except ValidationError:
        return None
    if proposal.operation != "record":
        return None
    matches = known.get((proposal.subject_id, proposal.kind, proposal.key), [])
    if len(matches) != 1:
        return None
    return {
        **proposal.model_dump(exclude_unset=True),
        "operation": "change",
        "record_id": matches[0],
        "subject_id": "",
        "key": "",
    }
