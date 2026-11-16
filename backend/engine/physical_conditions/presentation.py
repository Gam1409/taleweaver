"""Compact current facts; historical recall cannot resolve them by omission."""

import json
from typing import Any

from backend.engine.physical_conditions.ledger import read

PLAYER = "__player__"


def targets_from_actors(actors: dict) -> set[str]:
    targets = set(actors)
    for actor in actors.values():
        equipment = actor.get("equipment") or {}
        items = [
            *(actor.get("resolved_inventory") or []),
            *(equipment.values() if isinstance(equipment, dict) else []),
        ]
        for item in items:
            identifier = item.get("id") if isinstance(item, dict) else item
            if isinstance(identifier, str):
                targets.add(identifier)
    return targets


def context(
    state: Any,
    targets: set[str],
    *,
    public_only: bool = False,
    known_private: set[str] | None = None,
    include_resolved: bool = False,
) -> dict:
    try:
        ledger = read(getattr(state, "entity_states", None))
    except ValueError:
        return {"status": "unavailable", "note": "Existing conditions are not confirmed resolved."}
    visible = [
        row
        for row in ledger.conditions.values()
        if row.target_id in targets
        and (
            not public_only
            or row.visibility == "public"
            or row.target_id in (known_private or {PLAYER})
        )
    ]
    rows = [
        {
            key: getattr(row, key)
            for key in (
                "id",
                "target_id",
                "kind",
                "part",
                "status",
                "detail",
                "visibility",
                "visual_detail",
                "visual_region",
            )
        }
        for row in visible
        if row.status != "resolved"
    ]
    result = {"status": "available", "active": rows}
    if include_resolved:
        # Keep explicit negative facts compact; an old "open wound" detail is no
        # longer its current description. Missing records do not prove resolution.
        result["resolved"] = [
            {key: getattr(row, key) for key in ("id", "target_id", "kind", "part", "status")}
            for row in visible
            if row.status == "resolved"
        ]
    return result


def own_conditions(state: Any, actor_id: str) -> dict:
    return context(state, {actor_id})


def narration_block(
    state: Any,
    actors: dict,
    *,
    detailed: bool,
    visible_item_ids: set[str] | None = None,
) -> str:
    from backend.engine.clothing.projection import visible_character

    public_targets = set(actors) | (visible_item_ids or set())
    player_targets = {PLAYER}
    for identifier, actor in actors.items():
        items = actor.get("resolved_inventory", [])
        if identifier == PLAYER:
            player_targets.update(targets_from_actors({identifier: actor}))
            public_targets.update(player_targets)
            continue
        visual = visible_character(
            actor.get("visual_profile"), items, detailed=detailed, equipment=actor.get("equipment")
        )
        if visual:
            public_targets.update(row["item_id"] for row in visual["clothing"])
    data = context(
        state,
        public_targets,
        public_only=True,
        known_private=player_targets,
        include_resolved=True,
    )
    if not data.get("active") and not data.get("resolved") and data["status"] == "available":
        return ""
    return (
        "\nPERSISTENT PHYSICAL CONDITIONS (current saved facts):\n"
        + json.dumps(data, ensure_ascii=False)
        + "\nOmission from recent prose does not heal, clean or remove these conditions. "
        "Treatment is not complete healing; partial removal leaves a remaining condition. "
        "Explicit resolved records supersede older descriptions of that condition. "
        "Item state dimensions supersede obsolete state in intrinsic descriptions and old prose. "
        "Empty, clean, smoothed and depleted are retained states, not missing items. "
        "These facts do not establish currently exposed skin or another NPC's private knowledge. "
        "Respect current clothing and perspective. Mention conditions when relevant, not as a repeated checklist.\n"
    )
