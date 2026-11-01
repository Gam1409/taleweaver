"""Bind extracted facts to a narration revision and retract replacements."""

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from backend.engine.scene_staging import props
from backend.engine.scene_staging.state import KEY, digest


def _facts(data: dict) -> list[dict]:
    return [
        actor[field]
        for actor in data.get("actors", {}).values()
        for field in ("posture", "placement")
        if isinstance(actor.get(field), dict)
    ]


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
    affected = data.get("source_message_id") == message_id or any(
        fact.get("source_message_id") == message_id for fact in _facts(data)
    )
    if affected or not data.get("source_message_id"):
        data.update(status="unconfirmed", actors={})
        state.entity_states = {**state.entity_states, KEY: data}


def remap(entity_states: dict, message_ids: dict[str, str]) -> dict:
    result = props.remap(deepcopy(entity_states), message_ids)
    data = result.get(KEY)
    if not isinstance(data, dict):
        return result
    sources = [data, *_facts(data)]
    if any(source.get("source_message_id") not in message_ids for source in sources):
        data.update(status="unconfirmed", actors={})
        data.pop("source_message_id", None)
        return result
    for source in sources:
        source["source_message_id"] = message_ids[source["source_message_id"]]
    return result
