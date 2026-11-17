"""Bounded discovery over an observer's complete accessible view, not the prompt index."""

import json
from typing import TYPE_CHECKING

from backend.engine.chpm import agent_observable, host_observations

if TYPE_CHECKING:
    from backend.engine.chpm.agent_tools import Tools

MAX_MATCHES = 8
MAX_SEARCH_CHARS = 2000


def find(tools: "Tools", query: str) -> dict:
    """Return handles only; exact inspection supplies citable current state."""
    view = agent_observable.current(tools)
    if view is None:
        return {"status": "unavailable_view"}
    term = query.casefold().strip()
    rows = [
        {"id": key, "name": value["name"], "kind": value["kind"]}
        for key, value in view.entities.items()
        if term and (term in key.casefold() or term in value["name"].casefold())
    ]
    rows.sort(key=lambda row: (row["id"] != query, row["name"].casefold() != term, row["id"]))
    selected = rows[:MAX_MATCHES]
    while True:
        result = {
            "status": "ok",
            "matches": len(rows),
            "results": selected,
            "omitted_matches": len(rows) - len(selected),
        }
        if len(json.dumps(result, ensure_ascii=False)) <= MAX_SEARCH_CHARS:
            return result
        selected.pop()


def scene(tools: "Tools") -> dict:
    """Public room context only; own/private character facts use inspect_self/entity."""
    view = agent_observable.current(tools)
    facts = host_observations.previous(tools.mind)
    if view is None or facts is None:
        return {"status": "unavailable_view"}
    body = {
        "observation": "current_observable_scene",
        "scene_id": view.scene_id,
        "recorded_facts_are_exhaustive": False,
        "visible_actors": [
            {"id": row["id"], "name": row["name"]}
            for row in view.entities.values()
            if row["kind"] == "actor"
        ],
        "scene_facts": [row.model_dump(mode="json") for row in facts.scene_facts or ()],
        "scene_knowledge": "recorded_only" if facts.scene_facts is not None else "unavailable",
        "routes_knowledge": "unavailable",
        **view.scene,
        "omitted": {},
    }
    return agent_observable.publish(tools, body)
