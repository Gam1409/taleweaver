"""Bind extracted facts to a narration revision and retract replacements."""

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
        actor[field] for field in ("posture", "placement") if isinstance(actor.get(field), dict)
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
        if not fact.get("source_revision_id") and fact.get("source_hash") == data["source_hash"]:
            fact.update(source)
    state.entity_states = {**(state.entity_states or {}), KEY: data}


def retract(state: Any, message_id: str) -> None:
    data = deepcopy((state.entity_states or {}).get(KEY))
    if not isinstance(data, dict):
        return
    affected = {
        actor_id
        for actor_id, actor in _actors(data).items()
        if any(
            not fact.get("source_message_id") or fact.get("source_message_id") == message_id
            for fact in _actor_facts(actor)
        )
    }
    if not data.get("source_message_id") or data.get("source_message_id") == message_id:
        _remove_frame(data)
    _unconfirm(data, affected)
    state.entity_states = {**state.entity_states, KEY: data}


def remap(entity_states: dict, message_ids: dict[str, str]) -> dict:
    result = props.remap(deepcopy(entity_states), message_ids)
    data = result.get(KEY)
    if not isinstance(data, dict):
        return result
    affected = {
        actor_id
        for actor_id, actor in _actors(data).items()
        if any(fact.get("source_message_id") not in message_ids for fact in _actor_facts(actor))
    }
    _unconfirm(data, affected)
    for source in _facts(data):
        source["source_message_id"] = message_ids[source["source_message_id"]]
    source_id = message_ids.get(data.get("source_message_id", ""))
    if not source_id:
        _remove_frame(data)
        _unconfirm(data, set())
        return result
    data["source_message_id"] = source_id
    return result
