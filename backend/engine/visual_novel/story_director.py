"""NPC initiative inside the existing VN continuity request, with world validation."""

import json
import logging
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from backend.engine.npc_presence import physically_present
from backend.engine.rule_engine import EntityMovement
from backend.engine.visual_novel.config import read_settings
from backend.engine.visual_novel.scene_focus import (
    STATE_KEY,
    focus_context,
    focus_reminder,
    record_focus,
    stage_focus,
)
from backend.engine.visual_novel.story_prompts import NARRATOR_INITIATIVE

MAX_RECENT = 4
logger = logging.getLogger(__name__)


class StoryBeat(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    npc_id: str = Field(min_length=1, max_length=64)
    kind: Literal["dialogue", "activity", "departure"]
    relation: Literal["continue", "transition"] = "continue"
    purpose: str = Field(min_length=1, max_length=300)
    action: str = Field(min_length=1, max_length=600)
    destination_id: str | None = Field(default=None, max_length=64)


def optional_beat(value: Any) -> StoryBeat | None:
    if value is None:
        return None
    try:
        return StoryBeat.model_validate(value)
    except ValidationError:
        logger.warning("Discarding malformed optional VN story initiative")
        return None


def _states(state: Any) -> dict:
    value = getattr(state, "entity_states", None)
    return value if isinstance(value, dict) else {}


def _override(state: Any, npc: Any) -> dict:
    value = _states(state).get(npc.id)
    return value if isinstance(value, dict) else {}


def _available(state: Any, npc: Any) -> bool:
    override = _override(state, npc)
    return (
        getattr(npc, "entity_type", None) == "NPC"
        and override.get("current_scene_id", npc.current_scene_id) == state.current_scene_id
        and physically_present(npc, state)
        and not override.get("is_hidden", getattr(npc, "is_hidden", False))
        and not override.get("is_defeated", getattr(npc, "is_defeated", False))
    )


def _movable(state: Any, npc: Any, destination: str) -> bool:
    override = _override(state, npc)
    movable = override.get("moveable")
    if movable is None:
        movable = bool(getattr(npc, "moveable", False)) or (
            str(getattr(npc, "movement_type", "")).upper() == "MOVABLE"
        )
    allowed = override.get("allowed_scenes", getattr(npc, "allowed_scenes", None)) or []
    return bool(movable) and (
        not allowed or destination.upper() in {str(item).upper() for item in allowed}
    )


def recent_directions(state: Any) -> list[dict]:
    raw = _states(state).get(STATE_KEY, {})
    entries = raw.get("recent", []) if isinstance(raw, dict) else []
    if not isinstance(entries, list):
        return []
    result = []
    for entry in entries[-MAX_RECENT:]:
        try:
            beat = StoryBeat.model_validate(entry.get("beat") if isinstance(entry, dict) else None)
        except ValidationError:
            continue
        result.append(
            {"message_id": str(entry.get("message_id", ""))[:64], "beat": beat.model_dump()}
        )
    return result


def direction_context(manager: Any, entities: list[Any], exits: list[dict]) -> dict:
    """Private bounded planning context; never copied into public character cards."""
    state = manager.state
    adventure = getattr(manager, "adventure", None)
    present = [npc for npc in entities if _available(state, npc)]
    destinations = {
        str(edge["to_scene_id"])
        for edge in exits
        if edge.get("to_scene_id") and not edge.get("is_locked")
    }
    cast = [
        {
            "id": npc.id,
            "character": str(getattr(npc, "character", "") or "")[:200],
            "goal": str(getattr(npc, "goal", "") or "")[:300],
            "departure_destinations": sorted(
                destination for destination in destinations if _movable(state, npc, destination)
            ),
        }
        for npc in present
    ]
    return {
        "premise": str(getattr(state, "plot", None) or getattr(adventure, "plot", "") or "")[:1200],
        "guidance": str(
            getattr(state, "walkthrough", None) or getattr(adventure, "walkthrough", "") or ""
        )[:800],
        "pace": read_settings(state).pace,
        "characters": cast,
        "provisional_scene_orientation_not_facts": focus_context(state),
        "recent_attempted_beats_not_facts": [
            {
                "npc_id": entry["beat"]["npc_id"],
                "kind": entry["beat"]["kind"],
                "purpose": entry["beat"]["purpose"][:120],
                "action": entry["beat"]["action"][:240],
            }
            for entry in recent_directions(state)[-2:]
        ],
    }


def stage_direction(
    manager: Any,
    proposal: Any,
    event: Any,
    entities: list[Any],
    exits: list[dict],
    *,
    history: list[dict] | None = None,
) -> None:
    """Validate initiative independently; existing turn guardrails still run afterwards."""
    manager._vn_story_beat = None
    stage_focus(manager, proposal, history or [])
    beat = getattr(proposal, "story_beat", None)
    if beat is None:
        return
    npc = _eligible_actor(manager.state, beat, event, entities)
    if npc is None:
        return
    if beat.kind == "departure":
        if not _valid_departure(manager.state, npc, beat.destination_id, exits):
            return
        event.moved_entities = [
            *(event.moved_entities or []),
            EntityMovement(entity_id=npc.id, to_scene_id=beat.destination_id),
        ]
    elif beat.destination_id:
        return
    manager._vn_story_beat = beat


def _eligible_actor(state: Any, beat: StoryBeat, event: Any, entities: list[Any]) -> Any:
    if event.new_scene_id and event.new_scene_id != state.current_scene_id:
        return None
    npc = next((npc for npc in entities if npc.id == beat.npc_id), None)
    if npc is None or not _available(state, npc):
        return None
    # Do not overwrite an action already resolved for this NPC in the same turn.
    if any(move.entity_id == npc.id for move in event.moved_entities or []):
        return None
    if any(
        update.entity_id == npc.id and update.presence not in (None, "present")
        for update in event.updated_entities or []
    ):
        return None
    return npc


def _valid_departure(state: Any, npc: Any, destination: str | None, exits: list[dict]) -> bool:
    if not destination or destination == state.current_scene_id:
        return False
    return _movable(state, npc, destination) and any(
        edge.get("to_scene_id") == destination
        and edge.get("from_scene_id", state.current_scene_id) == state.current_scene_id
        and not edge.get("is_locked")
        for edge in exits
    )


def direction_reminder(manager: Any, event: Any) -> str:
    """Never narrate a departure rejected by the normal movement guardrails."""
    beat = getattr(manager, "_vn_story_beat", None)
    orientation = focus_reminder(manager)
    if beat is None:
        return orientation
    if beat.kind == "departure" and not any(
        move.entity_id == beat.npc_id and move.to_scene_id == beat.destination_id
        for move in getattr(event, "moved_entities", None) or []
    ):
        manager._vn_story_beat = None
        return orientation
    return "\n\n".join(
        part
        for part in (
            orientation,
            NARRATOR_INITIATIVE + json.dumps(beat.model_dump(), ensure_ascii=False),
        )
        if part
    )


def record_direction(manager: Any, message_id: str, *, completed: bool) -> None:
    """Retain attempted direction, not invented memories; replay snapshots rewind it."""
    if not completed:
        return
    record_focus(manager, message_id)
    beat = getattr(manager, "_vn_story_beat", None)
    if beat is None:
        return
    recent = [
        entry for entry in recent_directions(manager.state) if entry["message_id"] != message_id
    ]
    recent.append({"message_id": message_id, "beat": beat.model_dump()})
    manager.state.entity_states = {
        **_states(manager.state),
        STATE_KEY: {
            **_states(manager.state).get(STATE_KEY, {}),
            "version": 1,
            "recent": recent[-MAX_RECENT:],
        },
    }
