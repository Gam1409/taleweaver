"""Bind extracted facts to a narration revision and retract replacements."""

from collections.abc import Callable
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from backend.engine.scene_staging import props
from backend.engine.scene_staging.state import KEY, digest


def _actors(data: dict) -> dict[str, dict]:
    actors = data.get("actors", {})
    if not isinstance(actors, dict) or any(not isinstance(row, dict) for row in actors.values()):
        raise ValueError("Stored scene staging actors require repair.")
    return actors


def _actor_facts(actor: dict) -> list[dict]:
    return [
        actor[field]
        for field in ("posture", "placement", "command")
        if isinstance(actor.get(field), dict)
    ]


def _facts(data: dict) -> list[dict]:
    return [fact for actor in _actors(data).values() for fact in _actor_facts(actor)]


def _remove_frame(data: dict) -> None:
    data.pop("source_message_id", None)
    data.pop("source_revision_id", None)
    data["source_hash"] = ""
    data["explicit"] = []


def _unconfirm(data: dict, actor_ids: set[str]) -> None:
    actors = _actors(data)
    for actor_id in actor_ids:
        actors.pop(actor_id, None)
    previous = set(data.get("unconfirmed_actors") or ())
    data["unconfirmed_actors"] = sorted(previous | actor_ids)
    if not actors and not data.get("source_message_id"):
        data["status"] = "unconfirmed"


def _prune_actor(actor: dict, invalid: Callable[[dict], bool]) -> bool:
    affected = [
        field
        for field in ("posture", "placement", "command")
        if isinstance(actor.get(field), dict) and _invalid_source(actor[field], invalid)
    ]
    for field in affected:
        actor.pop(field)
    return bool(affected) and not _actor_facts(actor)


def _invalid_source(fact: dict, invalid: Callable[[dict], bool]) -> bool:
    cause = fact.get("cause")
    return invalid(fact) or isinstance(cause, dict) and invalid(cause)


def _prune(data: dict, invalid: Callable[[dict], bool]) -> None:
    """Sources own individual fields; an unrelated fact can retain the actor."""
    removed = {
        actor_id for actor_id, actor in _actors(data).items() if _prune_actor(actor, invalid)
    }
    _unconfirm(data, removed)


def stamp(state: Any, message: Any) -> None:
    data = deepcopy((state.entity_states or {}).get(KEY))
    if not isinstance(data, dict) or data.get("source_hash") != digest(message.content):
        return
    source = {
        "source_message_id": message.id,
        "source_revision_id": message.revision_id,
        "extracted_at": datetime.now(timezone.utc).isoformat(),
    }
    data.update(source)
    for fact in _facts(data):
        if (
            fact.get("source_kind") != "command"
            and not fact.get("source_revision_id")
            and fact.get("source_hash") == data["source_hash"]
        ):
            fact.update(source)
    state.entity_states = {**(state.entity_states or {}), KEY: data}


def retract(state: Any, message_id: str) -> None:
    data = deepcopy((state.entity_states or {}).get(KEY))
    if not isinstance(data, dict):
        return
    if not data.get("source_message_id") or data.get("source_message_id") == message_id:
        _remove_frame(data)
    _prune(
        data,
        lambda fact: not fact.get("source_message_id") or fact["source_message_id"] == message_id,
    )
    state.entity_states = {**state.entity_states, KEY: data}


def remap(entity_states: dict, message_ids: dict[str, str]) -> dict:
    result = props.remap(deepcopy(entity_states), message_ids)
    data = result.get(KEY)
    if not isinstance(data, dict):
        return result
    _prune(data, lambda fact: fact.get("source_message_id") not in message_ids)
    facts = _facts(data)
    sources = [*facts, *[fact["cause"] for fact in facts if isinstance(fact.get("cause"), dict)]]
    for source in {id(value): value for value in sources}.values():
        source["source_message_id"] = message_ids[source["source_message_id"]]
    source_id = message_ids.get(data.get("source_message_id", ""))
    if not source_id:
        _remove_frame(data)
        _unconfirm(data, set())
        return result
    data["source_message_id"] = source_id
    return result


def _actor_reference(record: dict, field: str, previous: str, current: str) -> None:
    if record.get(field) == previous:
        record[field] = current


def _placement_actor(value: Any, previous: str, current: str) -> None:
    if isinstance(value, dict) and value.get("target_kind") == "character":
        _actor_reference(value, "target", previous, current)


def _actor_references(actor: dict, previous: str, current: str) -> None:
    _placement_actor(actor.get("placement"), previous, current)
    for fact in _actor_facts(actor):
        _actor_reference(fact, "command_actor_id", previous, current)
        _placement_actor(fact.get("requested_placement"), previous, current)
        if isinstance(cause := fact.get("cause"), dict):
            _actor_reference(cause, "performer_id", previous, current)


def _ancillary_records(data: dict, field: str) -> list[dict]:
    values = data.get(field)
    return (
        [value for value in values if isinstance(value, dict)] if isinstance(values, list) else []
    )


def _stage_references(data: dict, previous: str, current: str) -> None:
    for field in ("unconfirmed_actors", "invalidated_placements"):
        if isinstance(values := data.get(field), list):
            data[field] = [current if value == previous else value for value in values]
    for atom in _ancillary_records(data, "explicit"):
        if isinstance(atom.get("participants"), list):
            atom["participants"] = [
                current if value == previous else value for value in atom["participants"]
            ]
    protected = data.get("command_protected_fields")
    if isinstance(protected, dict) and previous in protected:
        if current in protected:
            raise ValueError("Ambiguous staging protected fields cannot be merged during a copy.")
        protected[current] = protected.pop(previous)
    for denial in _ancillary_records(data, "rejected_command_pose_changes"):
        _actor_reference(denial, "actor_id", previous, current)


def _staging_actor(data: dict, previous: str, current: str) -> None:
    actors = _actors(data)
    if previous in actors:
        if current in actors:
            raise ValueError("Ambiguous staging actors cannot be merged during a session copy.")
        actors[current] = actors.pop(previous)
    for actor in actors.values():
        _actor_references(actor, previous, current)
    _stage_references(data, previous, current)


def _prop_actor(data: dict, previous: str, current: str) -> None:
    for item in _ancillary_records(data, "items"):
        _actor_reference(item, "owner_id", previous, current)


def remap_actor(entity_states: dict, previous: Any, current: str) -> dict:
    """Rebind an avatar's schema-defined staging references, never evidence or request hashes."""
    result = deepcopy(entity_states)
    if not isinstance(previous, str) or not previous or previous == current:
        return result
    if isinstance(data := result.get(KEY), dict):
        _staging_actor(data, previous, current)
    if isinstance(placed := result.get(props.KEY), dict):
        _prop_actor(placed, previous, current)
    return result
