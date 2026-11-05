"""Versioned pilot contracts. No transport, database, or Concordia dependencies."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, model_validator


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Settings(Contract):
    mode: Literal["off", "shadow", "live"] = "off"
    actor_ids: list[str] = Field(default_factory=list, max_length=3)
    model_role: Literal["small", "complex"] = "complex"
    max_output_tokens: int = Field(default=1200, ge=512, le=2048, strict=True)
    max_input_chars: int = Field(default=24000, ge=8000, le=48000, strict=True)
    max_calls_per_turn: int = Field(default=6, ge=1, le=8, strict=True)

    @model_validator(mode="after")
    def valid_selection(self) -> "Settings":
        if len(set(self.actor_ids)) != len(self.actor_ids):
            raise ValueError("Choose each NPC only once.")
        if any(not value.strip() or len(value) > 100 for value in self.actor_ids):
            raise ValueError("Invalid NPC identifier.")
        if self.mode != "off" and not self.actor_ids:
            raise ValueError("Choose at least one NPC.")
        minimum = len(self.actor_ids) + (1 if self.mode == "live" else 0)
        if self.mode != "off" and self.max_calls_per_turn < minimum:
            raise ValueError("The call budget must cover the selected NPCs and live validation.")
        return self


class Observation(Contract):
    session_id: str
    message_id: str
    revision_id: str | None = None
    content_hash: str
    sequence: int = Field(ge=0)
    scene_id: str
    minute: int = Field(ge=0)
    # This is an unverified request, never a world fact or a belief update.
    player_request: str = Field(max_length=6000)


class Candidate(Contract):
    kind: Literal["CONTINUE", "INITIATE", "ACCEPT", "REFUSE", "NEGOTIATE", "CLARIFY", "DEFER"]
    intention: str = Field(min_length=1, max_length=400)
    goal_alignment: Literal["supports", "neutral", "conflicts", "unknown"] = "unknown"
    goal_quote: str = Field(default="", max_length=300)
    reconsider_if: str = Field(min_length=1, max_length=200)


class Proposal(Contract):
    candidates: list[Candidate] = Field(min_length=2, max_length=4)
    appraisal: str = Field(max_length=300)


class Decision(Contract):
    actor_id: str
    observation: Observation
    context_hash: str
    proposal: Proposal
    selected: Candidate
    policy_version: Literal["goal-first-v1"] = "goal-first-v1"
    status: Literal["selected", "delivered", "shadow"] = "selected"
    reply_id: str | None = None
    reply_revision: str | None = None
    reply_hash: str | None = None
    spoken_evidence: str = ""


class Usage(Contract):
    calls: int = 0
    input_chars: int = 0
    output_chars: int = 0
    repairs: int = 0
    status: Literal["idle", "prepared", "validated", "shadow", "failed"] = "idle"
    detail: str = ""


class KernelState(Contract):
    schema_version: Literal[1] = 1
    revision: int = Field(default=0, ge=0)
    settings: Settings = Field(default_factory=Settings)
    # A high-water record per actor rejects old events without an unbounded journal.
    actors: dict[str, Decision] = Field(default_factory=dict, max_length=3)
    usage: Usage = Field(default_factory=Usage)


class SpokenEvidence(Contract):
    actor_id: str
    quote: str = Field(max_length=2000)


class Verdict(Contract):
    matches: StrictBool
    issues: list[str] = Field(default_factory=list, max_length=8)
    evidence: list[SpokenEvidence] = Field(default_factory=list, max_length=3)
