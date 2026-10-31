"""Small replaceable scene orientation, never a fact ledger or a transition gate."""

import json
import logging
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from backend.core.voice_repetition import strip_historical_voice_cues

STATE_KEY = "__vn_story_direction__"
logger = logging.getLogger(__name__)


class SceneFocus(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    current_goal: str = Field(default="", max_length=300)
    open_question: str = Field(default="", max_length=400)
    last_observed_change: str = Field(default="", max_length=400)
    evidence: str = Field(default="", max_length=700)


def optional_focus(value: Any) -> SceneFocus | None:
    if value is None:
        return None
    try:
        return SceneFocus.model_validate(value)
    except ValidationError:
        logger.warning("Discarding malformed optional VN scene focus")
        return None


def focus_context(state: Any) -> dict:
    states = getattr(state, "entity_states", None)
    direction = states.get(STATE_KEY, {}) if isinstance(states, dict) else {}
    stored = direction.get("focus", {}) if isinstance(direction, dict) else {}
    if not isinstance(stored, dict) or stored.get("scene_id") != state.current_scene_id:
        return {}
    focus = optional_focus(stored.get("orientation"))
    return focus.model_dump() if focus else {}


def stage_focus(manager: Any, proposal: Any, history: list[dict]) -> None:
    """Ground observations only in completed narration, never this turn's plan."""
    manager._vn_scene_focus = None
    focus = optional_focus(getattr(proposal, "scene_focus", None))
    if focus is None:
        return
    focus = focus.model_copy(deep=True)
    latest = next(
        (
            str(row.get("content", ""))
            for row in reversed(history)
            if row.get("role") == "assistant" and row.get("content")
        ),
        "",
    )
    if (
        not focus.evidence
        or focus.evidence not in strip_historical_voice_cues(latest)
        or not focus.last_observed_change
    ):
        focus.last_observed_change = ""
        focus.evidence = ""
    manager._vn_scene_focus = {
        "scene_id": manager.state.current_scene_id,
        "orientation": focus.model_dump(),
    }


def focus_reminder(manager: Any) -> str:
    staged = getattr(manager, "_vn_scene_focus", None)
    if not staged or staged["scene_id"] != manager.state.current_scene_id:
        return ""
    return (
        "SCENE ORIENTATION (private, provisional interpretation, not engine facts):\n"
        "Use the goal and open question to develop the scene, adapting or replacing them "
        "when circumstances change. The observed change refers to the previous reply; "
        "continue from it rather than reenacting it. Current state and actual dialogue "
        "take precedence. These notes do not establish memories or mechanical changes.\n"
        + json.dumps(staged["orientation"], ensure_ascii=False)
    )


def record_focus(manager: Any, message_id: str) -> None:
    """Called only on a completed turn, within its existing transaction and snapshot."""
    states = manager.state.entity_states or {}
    raw = states.get(STATE_KEY, {})
    direction = dict(raw) if isinstance(raw, dict) else {}
    staged = getattr(manager, "_vn_scene_focus", None)
    if staged and staged["scene_id"] == manager.state.current_scene_id:
        direction["focus"] = {**staged, "message_id": message_id}
    else:
        direction.pop("focus", None)
    if direction:
        manager.state.entity_states = {**states, STATE_KEY: direction}
    elif STATE_KEY in states:
        manager.state.entity_states = {
            key: value for key, value in states.items() if key != STATE_KEY
        }
