"""Derived plans never survive a rewind, import or evidence replacement."""

from copy import deepcopy
from uuid import uuid4

KEY = "__visual_preparation__"


def reset(states: dict | None) -> dict:
    return {**(states or {}), KEY: {"epoch": uuid4().hex, "entries": {}}}


def without_cache(states: dict | None) -> dict:
    return {key: deepcopy(value) for key, value in (states or {}).items() if key != KEY}


def prune(states: dict, message_ids: set[str]) -> None:
    cache = states.get(KEY)
    if isinstance(cache, dict):
        cache["entries"] = {
            key: entry
            for key, entry in cache.get("entries", {}).items()
            if entry.get("message_id") in message_ids
        }
