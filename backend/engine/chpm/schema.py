"""Versioned pilot contracts. No transport, database, or Concordia dependencies."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, model_validator

from backend.engine.chpm.host_state import Mind


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Settings(Contract):
    mode: Literal["off", "shadow", "live"] = "off"
    actor_ids: list[str] = Field(default_factory=list, max_length=3)
    model_role: Literal["small", "complex"] = "complex"
    max_output_tokens: int = Field(default=1200, ge=512, le=2048, strict=True)
    max_input_chars: int = Field(default=24000, ge=8000, le=48000, strict=True)
    max_calls_per_turn: int = Field(default=6, ge=1, le=8, strict=True)
    memory_limit: int = Field(default=12, ge=0, le=24, strict=True)

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
    source_scene_id: str | None = None
    minute: int = Field(ge=0)
    # This is an unverified request, never a world fact or a belief update.
    player_request: str = Field(max_length=6000)
    perception_uncertain: bool = False


class Perception(Contract):
    actor_id: str
    quotes: list[str] = Field(default_factory=list, max_length=3)
    uncertain: StrictBool = False


class Projection(Contract):
    audience: list[Perception] = Field(max_length=3)


class MemoryEntry(Contract):
    source_message_id: str
    source_revision_id: str | None = None
    source_hash: str
    source_role: Literal["user", "assistant"]
    scene_id: str
    observer_id: str
    speaker_id: str
    kind: Literal["player_observation", "own_speech", "heard_speech"]
    quote: str = Field(min_length=1, max_length=2000)


class AgendaIntent(Contract):
    action: Literal["goal", "commitment", "withdraw", "report_done"]
    text: str = Field(min_length=1, max_length=300)
    entry_id: str | None = Field(default=None, min_length=1, max_length=64)

    @model_validator(mode="after")
    def valid_target(self) -> "AgendaIntent":
        if (self.action in {"withdraw", "report_done"}) != bool(self.entry_id):
            raise ValueError("Only closing an existing agenda entry requires its ID.")
        return self


class AgendaClosure(Contract):
    reason: Literal["withdraw", "report_done"]
    source: MemoryEntry


class AgendaEntry(Contract):
    id: str = Field(min_length=1, max_length=64)
    actor_id: str
    kind: Literal["goal", "commitment"]
    text: str = Field(min_length=1, max_length=300)
    source: MemoryEntry
    closure: AgendaClosure | None = None

    @model_validator(mode="after")
    def own_speech_only(self) -> "AgendaEntry":
        sources = [self.source] + ([self.closure.source] if self.closure else [])
        if any(
            item.observer_id != self.actor_id
            or item.speaker_id != self.actor_id
            or item.source_role != "assistant"
            or item.kind != "own_speech"
            for item in sources
        ):
            raise ValueError("Agenda evidence must be the owner's own assistant speech.")
        return self


ActionKind = Literal["CONTINUE", "INITIATE", "ACCEPT", "REFUSE", "NEGOTIATE", "CLARIFY", "DEFER"]


class CandidateBody(Contract):
    intention: str = Field(min_length=1, max_length=400)
    goal_alignment: Literal["supports", "neutral", "conflicts", "unknown"] = "unknown"
    goal_quote: str = Field(default="", max_length=300)
    reconsider_if: str = Field(min_length=1, max_length=200)
    agenda_change: AgendaIntent | None = None


class Candidate(CandidateBody):
    kind: ActionKind


class Proposal(Contract):
    candidates: list[Candidate] = Field(min_length=2, max_length=4)
    appraisal: str = Field(max_length=300)


class ProposalOptions(Contract):
    candidates: dict[ActionKind, CandidateBody] = Field(min_length=2, max_length=4)
    appraisal: str = Field(max_length=300)

    def canonical(self) -> Proposal:
        return Proposal(
            candidates=[
                Candidate(kind=kind, **body.model_dump())
                for kind, body in sorted(self.candidates.items())
            ],
            appraisal=self.appraisal,
        )


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
    memory_evictions: int = 0


class KernelState(Contract):
    schema_version: Literal[1] = 1
    revision: int = Field(default=0, ge=0)
    settings: Settings = Field(default_factory=Settings)
    # A high-water record per actor rejects old events without an unbounded journal.
    actors: dict[str, Decision] = Field(default_factory=dict, max_length=3)
    memories: dict[str, list[MemoryEntry]] = Field(default_factory=dict, max_length=3)
    agenda: list[AgendaEntry] = Field(default_factory=list, max_length=256)
    minds: dict[str, Mind] = Field(default_factory=dict, max_length=32)
    usage: Usage = Field(default_factory=Usage)

    @model_validator(mode="after")
    def bounded_observer_memory(self) -> "KernelState":
        if any(actor != mind.genesis.scope.observer_id for actor, mind in self.minds.items()):
            raise ValueError("Psychological state is indexed under another NPC.")
        if len({entry.id for entry in self.agenda}) != len(self.agenda):
            raise ValueError("Duplicate CHPM agenda ID.")
        for actor, entries in self.memories.items():
            if len(entries) > 24 or any(entry.observer_id != actor for entry in entries):
                raise ValueError("Invalid CHPM observer memory window.")
        return self


class SpokenEvidence(Contract):
    actor_id: str
    quote: str = Field(max_length=2000)


class HeardSpeech(SpokenEvidence):
    speaker_id: str


class AgendaEvidence(SpokenEvidence):
    quote: str = Field(min_length=1, max_length=600)


class Verdict(Contract):
    matches: StrictBool
    issues: list[str] = Field(default_factory=list, max_length=8)
    evidence: list[SpokenEvidence] = Field(default_factory=list, max_length=3)
    heard: list[HeardSpeech] = Field(default_factory=list, max_length=12)
    agenda_evidence: list[AgendaEvidence] = Field(default_factory=list, max_length=3)
