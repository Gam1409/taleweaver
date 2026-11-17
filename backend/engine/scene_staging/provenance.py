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
        if isinstance(actor.get(field), dict) and invalid(actor[field])
    ]
    for field in affected:
        actor.pop(field)
    return bool(affected) and not _actor_facts(actor)


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
    for source in _facts(data):
        source["source_message_id"] = message_ids[source["source_message_id"]]
    source_id = message_ids.get(data.get("source_message_id", ""))
    if not source_id:
        _remove_frame(data)
        _unconfirm(data, set())
        return result
    data["source_message_id"] = source_id
    return result
