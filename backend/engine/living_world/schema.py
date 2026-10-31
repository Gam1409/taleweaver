"""Versioned simulation contracts separate from public session data."""

from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.engine.living_world.decisions import PrivateNotes


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    living_world_enabled: bool = False
    mode: Literal["PAUSE", "CATCH_UP"] = "PAUSE"
    offline_time_scale: float = Field(default=1, ge=0, le=24)
    max_catchup_game_hours: float = Field(default=6, ge=0, le=72)
    max_events: int = Field(default=16, ge=0, le=128)
    max_wall_seconds: float = Field(default=2, ge=0, le=10)
    auto_catchup_on_resume: bool = False
    dialogue_choices_enabled: bool = False
    live_enabled: bool = False
    live_interval_seconds: int = Field(default=60, ge=20, le=600)
    allow_concurrent_requests: bool = False
    deliberation_enabled: bool = False
    decision_engine: Literal["native", "concordia"] = "native"
    auto_schedule: bool = False
    schedule_interval_minutes: int = Field(default=60, ge=15, le=1440)
    max_npcs: int = Field(default=4, ge=1, le=8)
    max_decisions_per_run: int = Field(default=1, ge=1, le=4)
    max_deliberations: int = Field(default=8, ge=0, le=128)
    decision_max_tokens: int = Field(default=256, ge=128, le=1024)


class Event(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(min_length=1, max_length=64)
    due: int = Field(ge=0)
    kind: Literal["WAIT", "MOVE", "MEET", "DECISION", "SOCIAL"]
    actor: str = Field(default="", max_length=100)
    participant: str = Field(default="", max_length=100)
    destination: str = Field(default="", max_length=100)
    dependencies: list[str] = Field(default_factory=list, max_length=16)
    status: Literal["PLANNED", "WAITING_FOR_LLM", "COMMITTED", "CANCELLED"] = "PLANNED"
    result: str = Field(default="", max_length=300)
    observed_by_player: bool = False
    attempts: int = Field(default=0, ge=0, le=2)
    speech: str = Field(default="", max_length=180)
    committed_at: int | None = Field(default=None, ge=0)


class Simulation(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    version: Literal[1] = 1
    timeline: str = Field(default_factory=lambda: str(uuid4()))
    revision: int = Field(default=0, ge=0)
    settings: Settings = Field(default_factory=Settings)
    cursor: int = Field(default=0, ge=0)
    target: int = Field(default=0, ge=0)
    offline_total_seen: float = Field(default=0, ge=0)
    fractional_minutes: float = Field(default=0, ge=0, lt=1)
    status: Literal["PAUSED", "RUNNING", "PARTIAL", "WAITING_FOR_LLM", "COMPLETE", "FAILED"] = (
        "PAUSED"
    )
    events: list[Event] = Field(default_factory=list, max_length=512)
    last_run_events: int = Field(default=0, ge=0)
    deliberation_attempts: int = Field(default=0, ge=0)
    schedule_next_due: int = Field(default=0, ge=0)
    private_notes: dict[str, PrivateNotes] = Field(default_factory=dict, max_length=128)

    @model_validator(mode="after")
    def validate_timeline(self) -> "Simulation":
        known: dict[str, int] = {}
        for event in self.events:
            if event.event_id in known or any(
                key not in known or known[key] > event.due for key in event.dependencies
            ):
                raise ValueError("Events require unique IDs and earlier causal prerequisites.")
            known[event.event_id] = event.due
        if self.target < self.cursor:
            raise ValueError("The target cannot precede the committed cursor.")
        return self


class SettingsUpdate(BaseModel):
    settings: Settings
    expected_revision: int = Field(ge=0)


class Command(BaseModel):
    expected_revision: int = Field(ge=0)


class PresenceUpdate(BaseModel):
    client_id: str = Field(min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9-]+$")
    active: bool
