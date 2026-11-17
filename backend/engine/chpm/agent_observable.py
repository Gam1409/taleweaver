"""Expose current scoped state as ordinary citable tool evidence with bounded views."""

import json
from copy import deepcopy
from typing import TYPE_CHECKING

from backend.engine.chpm.host_observations import previous
from backend.engine.chpm.host_state import Source, identifier, record

if TYPE_CHECKING:
    from backend.engine.chpm.agent_tools import Tools
    from backend.engine.chpm.observable_state import View

MAX_VIEW_CHARS = 2000
MAX_INDEX_CHARS = 1500
MAX_INDEX_ITEMS = 32


def current(tools: "Tools") -> "View | None":
    view = tools.observable
    observed = tools.observation
    if view is None or (
        view.session_id != observed.session_id
        or view.observer_id != tools.mind.genesis.scope.observer_id
        or view.message_id != observed.message_id
        or view.revision_id != observed.revision_id
        or view.content_hash != observed.content_hash
        or view.scene_id != observed.scene_id
    ):
        return None
    facts = previous(tools.mind)
    return (
        view
        if any(
            source.kind == "host_frame"
            and source.facts == facts
            and facts is not None
            and source.message_id == observed.message_id
            and source.revision_id == observed.revision_id
            and source.content_hash == observed.content_hash
            and facts.scene_id == observed.scene_id
            for source in tools.mind.sources.values()
        )
        else None
    )


def index(tools: "Tools") -> dict:
    view = current(tools)
    if view is None:
        return {}
    rows = [
        {"id": key, "name": str(value["name"])[:80], "kind": value["kind"]}
        for key, value in sorted(
            view.entities.items(),
            key=lambda item: (
                item[0] != view.observer_id,
                item[1].get("owner_id") != view.observer_id,
                item[0],
            ),
        )
    ]
    selected = rows[:MAX_INDEX_ITEMS]
    while len(json.dumps(selected, ensure_ascii=False)) > MAX_INDEX_CHARS:
        selected.pop()
    return {"observable_entities": selected, "omitted_entities": len(rows) - len(selected)}


def inspect(tools: "Tools", entity_id: str) -> dict:
    view = current(tools)
    if view is None or entity_id not in view.entities:
        return {"status": "unavailable_entity"}
    body = {
        "observation": "current_observable_state",
        "scene_id": view.scene_id,
        "recorded_conditions_are_exhaustive": False,
        **deepcopy(view.entities[entity_id]),
        "omitted": {},
    }
    return publish(tools, body)


def publish(tools: "Tools", body: dict) -> dict:
    """Pin a previously projected, bounded current observation without world mutation."""
    body = deepcopy(body)
    text = _pack(body)
    if text is None:
        return {"status": "view_budget_exhausted"}
    source = Source(
        message_id=tools.observation.message_id,
        revision_id=tools.observation.revision_id,
        content_hash=tools.observation.content_hash,
        role="user",
        speaker_id=tools.mind.genesis.scope.observer_id,
        kind="world_event",
        text=text,
    )
    result = tools.expose(identifier(source, tools.mind.genesis), source, full=True)
    if result["status"] == "ok":
        tools.mind = record(tools.mind, source, minute=tools.observation.minute)
    return result


def _pack(body: dict) -> str | None:
    while True:
        text = json.dumps(body, ensure_ascii=False, separators=(",", ":"))
        if len(text) <= MAX_VIEW_CHARS:
            return text
        key = next(
            (
                name
                for name in (
                    "recorded_conditions",
                    "visible_clothing",
                    "scene_facts",
                    "visible_actors",
                    "routes",
                )
                if body.get(name)
            ),
            None,
        )
        if key is None:
            return None
        body[key].pop()
        body["omitted"][key] = body["omitted"].get(key, 0) + 1
