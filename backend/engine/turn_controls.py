"""Host-issued, turn-local correlation for existing control records.

Snapshot fingerprints describe ordering; they are not a database revision or CAS.
The stream owner opens and closes attempts. Operations retain their captured
binding even if a later invocation reuses the same manager or saved input.
"""

import json
from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError

_ID = r"^[A-Za-z0-9_-]{1,100}$"
_HASH = r"^[a-f0-9]{64}$"


class ControlBindingError(ValueError):
    """A captured source no longer matches the active saved input."""

    code = "stale_input"


class Binding(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    attempt_id: str = Field(pattern=_ID)
    phase: str = Field(pattern=r"^[a-z_][a-z0-9_.:]{0,79}$")
    input_id: str | None = Field(default=None, max_length=100)
    input_revision: str | None = Field(default=None, max_length=100)
    input_hash: str = Field(min_length=1, max_length=100)
    state_revision: str = Field(pattern=_HASH)


class Operation(Binding):
    operation_id: str = Field(pattern=_ID)
    command_id: str | None = Field(default=None, max_length=100)
    tool_call_id: str | None = Field(default=None, max_length=128)
    actor_id: str | None = Field(default=None, max_length=100)
    tool: str = Field(min_length=1, max_length=80)


@dataclass
class Attempt:
    id: str
    parent_turn_id: str | None
    active: bool = True


def fingerprint(value: Any) -> str:
    return sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode()
    ).hexdigest()


def begin(manager: Any) -> Attempt:
    """Every invocation is a new attempt, including retries of the same input."""
    previous = getattr(manager, "_turn_control_attempt", None)
    if isinstance(previous, Attempt):
        previous.active = False
    attempt = Attempt(uuid4().hex, getattr(manager, "turn_id", None))
    manager._turn_control_attempt = attempt
    manager._turn_control_input = None
    manager._vn_item_rejection = None
    return attempt


def close(manager: Any, *, attempt: Attempt | None = None) -> None:
    attempt = attempt or getattr(manager, "_turn_control_attempt", None)
    if isinstance(attempt, Attempt):
        attempt.active = False


def _attempt(manager: Any) -> Attempt:
    attempt = getattr(manager, "_turn_control_attempt", None)
    return attempt if isinstance(attempt, Attempt) else begin(manager)


def bind_input(manager: Any, message: Any) -> None:
    """Called by the canonical saved-input owner, after its identity is assigned."""
    _attempt(manager)
    manager._turn_control_input = {
        "input_id": message.id,
        "input_revision": message.revision_id,
        "input_hash": sha256(message.content.encode()).hexdigest(),
    }


def state_revision(manager: Any) -> str:
    state = getattr(manager, "state", None)
    avatar = getattr(manager, "avatar", None)
    return fingerprint(
        {
            "state": {
                key: getattr(state, key, None)
                for key in (
                    "current_scene_id",
                    "in_game_time",
                    "entity_states",
                    "exit_states",
                    "inventory",
                    "quests",
                )
            },
            "avatar": {
                key: getattr(avatar, key, None)
                for key in ("inventory", "equipment", "visual_profile")
            },
        }
    )


def scope(manager: Any, phase: str, *, observation: Any = None) -> dict:
    """Capture immutable metadata once; a Turn may expose its captured control view."""
    captured = getattr(manager, "control", None)
    if not hasattr(manager, "game_id") and captured:
        return Binding.model_validate({**captured, "phase": phase}).model_dump()
    attempt = _attempt(manager)
    source = getattr(manager, "_turn_control_input", None) or {}
    if observation is not None:
        observed = {
            "input_id": observation.message_id,
            "input_revision": observation.revision_id,
            "input_hash": observation.content_hash,
        }
        if source and observed != source:
            raise ControlBindingError(
                "The observation belongs to a different saved input revision."
            )
        if getattr(observation, "session_id", getattr(manager, "game_id", None)) != getattr(
            manager, "game_id", None
        ):
            raise ControlBindingError("The observation belongs to a different session.")
        source = observed
    return Binding(
        attempt_id=attempt.id,
        phase=phase,
        input_id=source.get("input_id", getattr(manager, "_vn_player_message_id", None)),
        input_revision=source.get("input_revision"),
        input_hash=source.get("input_hash", fingerprint(None)),
        state_revision=state_revision(manager),
    ).model_dump()


def binding(raw: Mapping) -> Binding:
    return Binding.model_validate({key: raw[key] for key in Binding.model_fields if key in raw})


def bind_current(
    manager: Any, raw: Mapping, phase: str | None = None, *, observation: Any = None
) -> bool:
    """Check attempt/input identity; owner checks revalidate current world preconditions."""
    attempt = getattr(manager, "_turn_control_attempt", None)
    if not isinstance(attempt, Attempt) or not attempt.active:
        return False
    try:
        supplied = binding(raw)
        current = Binding.model_validate(
            scope(manager, phase or supplied.phase, observation=observation)
        )
    except (ValueError, TypeError, KeyError, ValidationError):
        return False
    if phase is not None and supplied.phase != phase:
        return False
    fields = ("attempt_id", "input_id", "input_revision", "input_hash")
    active_input = getattr(manager, "_vn_player_message_id", current.input_id)
    canonical = getattr(manager, "_turn_control_input", None)
    return (
        active_input == supplied.input_id
        and all(getattr(supplied, key) == getattr(current, key) for key in fields)
        and (
            canonical is None or all(getattr(supplied, key) == canonical[key] for key in fields[1:])
        )
    )


def operation(
    captured: Mapping,
    tool: str,
    *,
    actor_id: str | None = None,
    command_id: str | None = None,
    tool_call_id: str | None = None,
) -> Operation:
    return Operation(
        **binding(captured).model_dump(),
        operation_id="operation_" + uuid4().hex,
        command_id=command_id,
        tool_call_id=tool_call_id,
        actor_id=actor_id,
        tool=tool,
    )


def request_view(record: Operation) -> dict:
    """Expose one request binding; its observation already carries canonical input metadata."""
    return record.model_dump(include={"attempt_id", "operation_id", "phase", "state_revision"})


def rule_rejections(manager: Any, messages: list[str]) -> list[dict]:
    """Project existing turn-local rule denials without classifying their prose."""
    captured = scope(manager, "preliminary_rules")
    return [
        {
            **operation(captured, "rules_check").model_dump(exclude_none=True),
            "event_id": "event_" + uuid4().hex,
            "status": "blocked",
            "reason_code": "preliminary_rule_rejected",
            "message": "The preliminary rules check rejected a proposed change.",
            "diagnostic_detail": message,
        }
        for message in messages
    ]
