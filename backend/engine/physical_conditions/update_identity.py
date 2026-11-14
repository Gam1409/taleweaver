"""Discard only exact immutable echoes of an available existing condition."""

from typing import Any

from backend.engine.physical_conditions.schema import Condition, Ledger

_UPDATES = {"change", "treat", "reduce", "clean", "heal", "remove"}
_FIELDS = ("target_id", "kind", "part")


def normalize(raw: Any, ledger: Ledger, targets: set[str]) -> tuple[Any, tuple[str, ...]]:
    if not isinstance(raw, dict):
        return raw, ()
    operation, identifier = raw.get("operation"), raw.get("condition_id")
    if (
        not isinstance(operation, str)
        or operation not in _UPDATES
        or not isinstance(identifier, str)
    ):
        return raw, ()
    current = ledger.conditions.get(identifier.strip())
    if current is None or current.target_id not in targets or current.status == "resolved":
        return raw, ()
    fields = _matching_fields(raw, current)
    if not fields:
        return raw, ()
    return {key: value for key, value in raw.items() if key not in fields}, fields


def _matching_fields(raw: dict, current: Condition) -> tuple[str, ...]:
    classified = {
        field: _classify(field, raw[field], getattr(current, field))
        for field in _FIELDS
        if field in raw
    }
    if "conflict" in classified.values():
        return ()
    return tuple(field for field, status in classified.items() if status == "match")


def _classify(field: str, value: Any, expected: str) -> str:
    if value is None and field != "part":
        return "blank"
    if type(value) is not str:
        return "conflict"
    normalized = value if field == "kind" else value.strip()
    if not normalized and field != "kind":
        return "blank"
    return "match" if normalized == expected else "conflict"


def audit(index: int, identifier: str, fields: tuple[str, ...]) -> list[dict]:
    return (
        [{"proposal": index + 1, "condition_id": identifier, "fields": list(fields)}]
        if fields
        else []
    )
