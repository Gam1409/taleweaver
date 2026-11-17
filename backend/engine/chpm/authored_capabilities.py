"""Private, transient knowledge from the bound NPC's own authored card, without combat rules."""

import json
from copy import deepcopy
from typing import Any

from backend.engine.chpm.kernel import ChpmError

MAX_VIEW_CHARS = 6000
MAX_DESCRIPTION_CHARS = 1200
MAX_ABILITIES = 8
FIELD_LIMITS = {"id": 100, "name": 120, "description": 400}
KEY = "own_authored_capabilities"


def _ability(raw: Any) -> dict | None:
    if not isinstance(raw, dict):
        return None
    fields = {key: value for key in FIELD_LIMITS if isinstance(value := raw.get(key), str)}
    if not any(value.strip() for value in fields.values()):
        return None
    return {
        **{key: value[: FIELD_LIMITS[key]] for key, value in fields.items()},
        "omitted_characters": {
            key: len(value) - FIELD_LIMITS[key]
            for key, value in fields.items()
            if len(value) > FIELD_LIMITS[key]
        },
    }


def project(actor: Any) -> dict | None:
    """Preserve bounded original text; never infer skills, defaults, IDs or mechanical effects."""
    original = getattr(actor, "description", None)
    description = original if isinstance(original, str) else ""
    metadata = getattr(actor, "metadata_json", None)
    raw = metadata.get("special_actions") if isinstance(metadata, dict) else None
    if not description and (raw is None or raw == []):
        return None
    rows = raw if isinstance(raw, list) else []
    abilities = [view for item in rows[:MAX_ABILITIES] if (view := _ability(item)) is not None]
    result: dict[str, Any] = {
        "actor_id": str(actor.id),
        "source": "own_current_authored_card",
        "scope": "private_self_knowledge",
        "description": description[:MAX_DESCRIPTION_CHARS],
        "description_omitted_characters": max(0, len(description) - MAX_DESCRIPTION_CHARS),
        "abilities": abilities,
        "omitted_abilities": len(rows) - len(abilities),
        "catalog_status": "not_recorded"
        if raw is None
        else "available"
        if isinstance(raw, list)
        else "unavailable",
        "mechanical_execution": False,
        "meaning": (
            "Own authored capability descriptions may inform narrative intentions; they do not "
            "prove an action succeeded or authorize combat effects. Pinned personality remains "
            "separate. Other actors' abilities require witnessed or public evidence."
        ),
    }
    _fit(result)
    return result


def _fit(view: dict) -> None:
    while (size := len(json.dumps(view, ensure_ascii=False))) > MAX_VIEW_CHARS:
        if view["abilities"]:
            view["abilities"].pop()
            view["omitted_abilities"] += 1
            continue
        text = view["description"]
        if not text:
            raise ChpmError(
                "The authored capability view exceeds its budget; no identity was truncated."
            )
        view["description"] = text[: max(0, len(text) - (size - MAX_VIEW_CHARS))]
        view["description_omitted_characters"] += len(text) - len(view["description"])


def context_fields(supplied: dict, observer_id: str) -> dict:
    """Retain self-knowledge through both lookup protocols without making it citable evidence."""
    view = supplied.get(KEY)
    if view is None:
        return {}
    if not isinstance(view, dict) or view.get("actor_id") != observer_id:
        raise ChpmError("Authored capability knowledge belongs to another observer.")
    return {KEY: deepcopy(view)}


def lookup_fields(supplied: dict, observer_id: str) -> dict:
    """Keep exact self-knowledge and warnings, without repeating explanatory/default metadata."""
    selected = context_fields(supplied, observer_id)
    if not selected:
        return {}
    view = selected[KEY]
    compact = {
        key: view[key]
        for key in ("actor_id", "description", "catalog_status", "mechanical_execution")
        if key in view
    }
    compact.update(
        {
            key: view[key]
            for key in ("description_omitted_characters", "omitted_abilities")
            if view.get(key)
        }
    )
    if view.get("abilities"):
        compact["abilities"] = [
            {key: value for key, value in item.items() if key != "omitted_characters" or value}
            for item in view["abilities"]
        ]
    return {KEY: compact}
