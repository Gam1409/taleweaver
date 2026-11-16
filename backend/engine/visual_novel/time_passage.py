"""Explicit completed time skips use host arithmetic, separate from ordinary estimates."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, ValidationError, model_validator

MAX_PASSAGE_MINUTES = 365 * 24 * 60
_MINUTES = {"minutes": 1, "hours": 60, "days": 1440, "weeks": 10080}


class TimePassage(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    amount: StrictInt = Field(ge=1, le=MAX_PASSAGE_MINUTES)
    unit: Literal["minutes", "hours", "days", "weeks"]
    basis: Literal["elapsed", "future", "recalled", "uncertain"]
    evidence: str = Field(min_length=4, max_length=600)

    @property
    def minutes(self) -> int:
        return self.amount * _MINUTES[self.unit]

    @model_validator(mode="after")
    def bounded(self) -> "TimePassage":
        if self.minutes > MAX_PASSAGE_MINUTES:
            raise ValueError("The declared time skip exceeds one game year.")
        return self


def candidate(value: Any) -> Any:
    # Invalid optional fields are checked by the host without rejecting other intents.
    return value.model_dump() if isinstance(value, BaseModel) else value


def _cap(adventure: Any) -> int | None:
    raw = getattr(adventure, "max_time_per_turn", None)
    if raw is None:
        config = getattr(adventure, "time_config", None)
        raw = config.get("max_time_per_turn") if isinstance(config, dict) else None
    try:
        value = int(raw) if raw is not None else 0
    except (ValueError, TypeError):
        return None
    return value if value > 0 else None


def _duration(raw: Any, request: str, manager: Any) -> int:
    try:
        passage = TimePassage.model_validate(raw)
    except ValidationError as exc:
        raise ValueError("The optional time passage has invalid fields.") from exc
    if passage.basis != "elapsed" or passage.evidence not in request:
        raise ValueError("No exact current-player evidence of completed elapsed time.")
    system = (
        getattr(manager.state, "time_system", None)
        or getattr(manager.adventure, "time_system", None)
        or "calendar"
    )
    if system == "units":
        raise ValueError("Calendar durations cannot be converted to custom time units implicitly.")
    cap = _cap(manager.adventure)
    if cap is not None and passage.minutes > cap:
        raise ValueError("The explicit time passage exceeds the adventure's time limit per turn.")
    return passage.minutes


def apply(manager: Any, event: Any, raw: Any, request: str) -> None:
    if raw is None:
        return
    # A malformed/future/recalled skip must not fall back to a guessed multi-day duration.
    event.extra_time_minutes = 0
    try:
        elapsed = _duration(raw, request, manager)
    except ValueError as exc:
        event.narrative_description += " Time passage was not applied: " + str(exc)
        return
    event.time_override_minutes = int(manager.state.in_game_time or 0) + elapsed
    event.narrative_description += f" The declared completed passage advances the game clock by {elapsed} minutes; do not add another base duration."


INSTRUCTION = """
EXPLICIT TIME PASSAGE: for the player's declaration of completed elapsed time (e.g.
"Three days passed"), use time_passage={amount:3,unit:"days",basis:"elapsed",
evidence:"Three days passed"}, copying an exact contiguous quote from THIS player
message. The host converts units and applies the passage once. Set extra_time_minutes=0.
Use this for explicit completed waits/skips, including multiple days; ordinary
inferred activity still uses the bounded extra_time_minutes estimate.
Future appointments, wishes, hypotheticals, past recollections and another person's
off-screen story do not advance the current scene. Omit time_passage for them or
mark basis future/recalled/uncertain. Never invent an absolute clock override.
"""
