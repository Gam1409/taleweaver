"""Bind wear placements to saved narration and remap only their defined source fields."""

from copy import deepcopy
from hashlib import sha256
from typing import Any


def source_matches(source: dict, text: str) -> bool:
    quote = source.get("evidence")
    span = source.get("evidence_span")
    return (
        isinstance(quote, str)
        and bool(quote)
        and quote in text
        and source.get("content_hash") == sha256(text.encode()).hexdigest()
        and (
            span is None
            or isinstance(span, dict)
            and type(span.get("start")) is int
            and type(span.get("end")) is int
            and 0 <= span["start"] < span["end"] <= len(text)
            and text[span["start"] : span["end"]] == quote
        )
    )


def _stamp_profile(raw: Any, request_id: str, message: Any) -> Any:
    if not isinstance(raw, dict) or not isinstance(raw.get("worn"), list):
        return raw
    result = deepcopy(raw)
    for worn in result["worn"]:
        source = worn.get("source") if isinstance(worn, dict) else None
        if (
            isinstance(source, dict)
            and source.get("request_id") == request_id
            and not source.get("source_message_id")
            and source_matches(source, message.content)
        ):
            source["source_message_id"] = message.id
    return result


def stamp(manager: Any, message: Any) -> None:
    request_id = getattr(manager, "_vn_player_message_id", "")
    if not request_id:
        return
    avatar = getattr(manager, "avatar", None)
    if avatar is not None:
        raw = getattr(avatar, "visual_profile", None)
        avatar.visual_profile = _stamp_profile(raw, request_id, message)
    states = dict(manager.state.entity_states or {})
    for identifier, override in states.items():
        if isinstance(override, dict) and "visual_profile" in override:
            states[identifier] = {
                **override,
                "visual_profile": _stamp_profile(override["visual_profile"], request_id, message),
            }
    manager.state.entity_states = states


def remap_profile(raw: Any, message_ids: dict[str, str]) -> Any:
    if not isinstance(raw, dict) or not isinstance(raw.get("worn"), list):
        return deepcopy(raw)
    result = deepcopy(raw)
    for worn in result["worn"]:
        source = worn.get("source") if isinstance(worn, dict) else None
        if not isinstance(source, dict):
            continue
        for key in ("request_id", "source_message_id"):
            value = source.get(key)
            source[key] = message_ids.get(value) if isinstance(value, str) else None
    return result


def remap_states(states: dict, message_ids: dict[str, str]) -> dict:
    result = deepcopy(states)
    for override in result.values():
        if isinstance(override, dict) and "visual_profile" in override:
            override["visual_profile"] = remap_profile(override["visual_profile"], message_ids)
    return result
