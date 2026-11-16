"""Bounded older own-participation evidence projected from the existing journal."""

import json
from typing import Any

from backend.engine.living_world.schema import Event, Simulation
from backend.engine.memory_rag.ranking import tokens

MAX_RECALLED_EVENTS = 3
MAX_RECALLED_CHARS = 1200


def eligible(simulation: Simulation, decision: Event) -> list[Event]:
    boundary = max(simulation.cursor, decision.due)
    return [
        item
        for item in simulation.events
        if item.status == "COMMITTED"
        and item.kind in {"MOVE", "MEET", "SOCIAL"}
        and decision.actor in {item.actor, item.participant}
        and item.due <= decision.due
        and (item.committed_at is None or item.committed_at <= boundary)
        and item.result
    ]


def query(context: dict[str, Any]) -> str:
    """Only this actor's supplied context can guide its reference/event lookup."""
    actor, notes, scene = context["actor"], context["private_notes"], context["scene"]
    return "\n".join(
        [
            str(notes.get("goal", "")),
            str(actor.get("authored_goal", "")),
            str(notes.get("belief", "")),
            str(scene.get("description", "")),
            " ".join(context["observations"][-2:]),
            " ".join(item["name"] for item in context["participants"]),
        ]
    )[:3000]


def recall(simulation: Simulation, decision: Event, context: dict[str, Any]) -> list[dict]:
    events = eligible(simulation, decision)
    older = events[:-8]
    terms = tokens(query(context))
    scores = [(len(terms & tokens(item.result)), index, item) for index, item in enumerate(older)]
    ordered = [
        item for score, _, item in sorted(scores, key=lambda row: (-row[0], -row[1])) if score
    ]
    accessible = {item.event_id for item in events}
    selected: list[dict] = []
    for item in ordered:
        record = {
            "timeline": simulation.timeline,
            "event_id": item.event_id,
            "kind": item.kind,
            "due": item.due,
            "committed_at": item.committed_at,
            "result": item.result,
            "epistemic_status": (
                "observed utterance; assertions remain unverified"
                if item.kind == "SOCIAL"
                else "own committed participation; not proof of current state"
            ),
            "requires": [key for key in item.dependencies if key in accessible][:4],
        }
        if len(json.dumps([*selected, record], ensure_ascii=False)) <= MAX_RECALLED_CHARS:
            selected.append(record)
        if len(selected) == MAX_RECALLED_EVENTS:
            break
    return selected
