"""Only source-backed visible surfaces survive the current clothing projection."""

from typing import Any

from backend.engine.clothing.projection import visible_body_regions, visible_character

from .ledger import read
from .schema import KEY


def project(state: Any, actors: dict, *, detailed: bool, limit: int | None = 12) -> list[dict]:
    try:
        ledger = read(getattr(state, "entity_states", None))
    except ValueError:
        return []
    regions = _regions(actors, detailed)
    subjects = _subjects(actors, detailed)
    rows = [
        {
            "id": row.id,
            "target_id": row.target_id,
            "detail": row.visual_detail,
            "status": row.status,
            **subjects.get(row.target_id, {}),
        }
        for row in ledger.conditions.values()
        if row.status != "resolved"
        and row.visibility == "public"
        and row.visual_detail
        and row.latest.kind != "unavailable"
        and row.visual_region in regions.get(row.target_id, set())
    ]
    return rows if limit is None else rows[:limit]


def _subjects(actors: dict, detailed: bool) -> dict[str, dict]:
    subjects = {}
    for identifier, actor in actors.items():
        subjects[identifier] = {"actor_id": identifier}
        visual = visible_character(
            actor.get("visual_profile"),
            actor.get("resolved_inventory") or [],
            detailed=detailed,
            equipment=actor.get("equipment"),
        )
        if visual is None:
            continue
        subjects.update(
            {
                item["item_id"]: {"actor_id": identifier, "target_name": item["name"]}
                for item in visual["clothing"]
            }
        )
    return subjects


def retract(state: Any, message_id: str) -> None:
    """A prose edit revokes visual exposure evidence, preserving canonical physical facts."""
    if KEY not in (state.entity_states or {}):
        return
    ledger = read(state.entity_states)
    for row in ledger.conditions.values():
        if row.latest.kind == "narration" and row.latest.message_id == message_id:
            row.visual_detail, row.visual_region = "", None
    state.entity_states = {**state.entity_states, KEY: ledger.model_dump()}


def _regions(actors: dict, detailed: bool) -> dict[str, set]:
    regions = {}
    for identifier, actor in actors.items():
        profile, items, equipment = (
            actor.get("visual_profile"),
            actor.get("resolved_inventory") or [],
            actor.get("equipment"),
        )
        regions[identifier] = visible_body_regions(profile, items, equipment=equipment)
        visual = visible_character(profile, items, detailed=detailed, equipment=equipment)
        if visual is None:
            continue
        regions.update(
            {item["item_id"]: set(item["visible_regions"]) for item in visual["clothing"]}
        )
    return regions
