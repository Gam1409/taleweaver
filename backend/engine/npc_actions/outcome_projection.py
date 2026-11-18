"""Audience-safe narrative receipts; host publication and reconciliation stay complete."""

from collections.abc import Collection, Mapping
from copy import deepcopy

PROPERTY_TOOLS = frozenset({"change_item_state", "use_item"})
PROPERTY_FIELDS = frozenset({"dimension", "detail", "condition_id"})


def _omit(record: dict, fields: Collection[str], reason: str) -> dict:
    effect = record["effect"]
    record["effect"] = {key: value for key, value in effect.items() if key not in fields}
    record["effect_omitted"] = {"fields": sorted(fields), "reason": reason}
    return record


def _hidden_target(effect: dict, entities: Mapping[str, dict]) -> bool:
    return any(
        not isinstance(effect[key], str) or effect[key] not in entities
        for key in ("item_id", "target_id")
        if key in effect
    )


def _public_property(effect: dict, entities: Mapping[str, dict]) -> bool:
    identifier = effect.get("item_id")
    entity = entities.get(identifier) if isinstance(identifier, str) else None
    if entity is None:
        return False
    return any(
        condition.get("id") == effect.get("condition_id")
        and condition.get("kind") == "item_state"
        and condition.get("status") == "active"
        and condition.get("part") == effect.get("dimension")
        and condition.get("detail") == effect.get("detail")
        for condition in entity.get("recorded_conditions") or ()
    )


def project(record: dict, entities: Mapping[str, dict] | None) -> dict:
    """Copy a validated receipt using the full current public owner projection.

    Omission never changes operation status or host authority. A missing public
    frame cannot authorize disclosure, and current facts cannot relabel an older
    event with a newer value. Packed model views are not visibility evidence.
    """
    result = deepcopy(record)
    effect = result.get("effect")
    if not isinstance(effect, dict) or not effect:
        return result
    if entities is None:
        return _omit(result, set(effect), "public_view_unavailable")
    if _hidden_target(effect, entities):
        return _omit(result, set(effect), "target_not_publicly_observable")
    if result.get("tool") not in PROPERTY_TOOLS or _public_property(effect, entities):
        return result
    return _omit(result, PROPERTY_FIELDS.intersection(effect), "property_not_publicly_observable")
