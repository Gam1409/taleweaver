"""Session-scoped NPC presence, separate from discovery and map locations."""

import json
from typing import Any

PRESENCE_INSTRUCTION = """NPC PRESENCE: Use updated_entities.presence only for an actual,
completed departure or return: present (physically here), audible (outside the
immediate scene but explicitly still within hearing), absent (cannot participate).
A nearby doorway does not require creating a map location. Use moved_entities
for travel to another existing location; never bypass movement restrictions.
Review the latest completed narrator response for a missed departure/return,
then the current action. Do not infer movement from old history, plans, tomorrow,
yesterday, wishes, a request to leave, silence, or emotional withdrawal.
Absence persists until an actual return. Do not restore everyone each turn.
Do not use is_hidden for departures: that field controls discovery.
"""


def presence(entity: Any, state: Any = None) -> str:
    """Legacy entities default to physically present; location filtering is separate."""
    raw = entity if isinstance(entity, dict) else vars(entity)
    override: Any = {}
    if state is not None:
        override = (getattr(state, "entity_states", None) or {}).get(raw.get("id"), {})
    if not isinstance(override, dict):
        override = {}
    value = override.get("presence", raw.get("presence", "present"))
    return value if value in {"present", "audible", "absent"} else "present"


def physically_present(entity: Any, state: Any = None) -> bool:
    raw = entity if isinstance(entity, dict) else vars(entity)
    return raw.get("entity_type") != "NPC" or presence(entity, state) == "present"


def presence_context(entities: list[Any], state: Any) -> str:
    """Identity and availability only; no private thoughts or off-scene possessions."""
    cast = []
    for entity in entities:
        if entity.entity_type != "NPC":
            continue
        override = (state.entity_states or {}).get(entity.id) or {}
        scene = override.get("current_scene_id", entity.current_scene_id)
        if scene != state.current_scene_id or override.get("is_hidden", entity.is_hidden):
            continue
        cast.append({"id": entity.id, "name": entity.name, "presence": presence(entity, state)})
    return (
        "\nCURRENT NPC PRESENCE (authoritative, not historical memory):\n"
        + json.dumps(cast, ensure_ascii=False)
        + "\nOnly present NPCs may act here. Audible NPCs may speak from outside, "
        "but cannot touch or exchange items here. Absent NPCs cannot speak, hear "
        "or act here. Remembering someone does not bring them back. "
        "A departure or return requires an approved presence update or movement.\n"
    )


def movement_resolution(entities: list[Any], state: Any, event: Any) -> str:
    """Keep the latest approved cast beside narration, after historical dialogue."""
    moves = getattr(event, "moved_entities", None) or []
    if not moves:
        return ""
    known = {row.id: row for row in entities if row.entity_type == "NPC" and not row.is_hidden}
    outcomes = []
    for move in moves:
        actor = known.get(move.entity_id)
        override = (state.entity_states or {}).get(move.entity_id) or {}
        if actor is None or not override.get("remembered"):
            continue
        outcomes.append(
            {
                "npc_id": actor.id,
                "name": override.get("name", actor.name),
                "current_scene_id": override.get("current_scene_id", actor.current_scene_id),
            }
        )
    return (
        "NPC MOVEMENT RESOLUTION: "
        + json.dumps(outcomes, ensure_ascii=False)
        + presence_context(entities, state)
        + "Use this current cast after movement. Earlier dialogue cannot bring an NPC back. "
        "Only NPCs in this current scene may act beside the player."
    )
