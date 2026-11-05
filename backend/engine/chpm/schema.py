"""Versioned pilot contracts. No transport, database, or Concordia dependencies."""

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, model_validator

from backend.engine.chpm.host_state import Mind
from backend.engine.chpm.motivation_contracts import ResolvedMotive


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Settings(Contract):
    mode: Literal["off", "shadow", "live"] = "off"
    actor_ids: list[str] = Field(default_factory=list, max_length=20)
    max_active_npcs: int = Field(default=3, ge=1, le=20, strict=True)
    model_role: Literal["small", "complex"] = "complex"
    max_output_tokens: int = Field(default=1200, ge=512, le=8192, strict=True)
    max_input_chars: int = Field(default=24000, ge=8000, le=192000, strict=True)
    max_calls_per_turn: int = Field(default=8, ge=1, le=25, strict=True)
    memory_limit: int = Field(default=12, ge=0, le=24, strict=True)
    agent_steps: int = Field(default=0, ge=0, le=2, strict=True)

    @model_validator(mode="after")
    def valid_selection(self) -> "Settings":
        if len(set(self.actor_ids)) != len(self.actor_ids):
            raise ValueError("Choose each NPC only once.")
        if any(not value.strip() or len(value) > 100 for value in self.actor_ids):
            raise ValueError("Invalid NPC identifier.")
        if self.mode != "off" and not self.actor_ids:
            raise ValueError("Choose at least one NPC.")
        minimum = min(len(self.actor_ids), self.max_active_npcs) + (1 if self.mode == "live" else 0)
        if self.mode != "off" and self.max_calls_per_turn < minimum:
            raise ValueError("The call budget must cover the selected NPCs and live validation.")
        return self


class Observation(Contract):
    session_id: str
    message_id: str
    revision_id: str | None = None
    content_hash: str
    sequence: int = Field(ge=0)
    # Host turn order; old snapshots retain None and their timestamp fallback.
    turn_revision: int | None = Field(default=None, ge=0, strict=True)
    scene_id: str
    source_scene_id: str | None = None
    minute: int = Field(ge=0)
    # This is an unverified request, never a world fact or a belief update.
    player_request: str = Field(max_length=6000)
    perception_uncertain: bool = False
    perception_kinds: list[str] = Field(default_factory=list, max_length=32)


class Perception(Contract):
    actor_id: str
    quotes: list[str] = Field(default_factory=list, max_length=32)
    uncertain: StrictBool = False
    engaged: StrictBool = False
    coverage: dict[str, str] = Field(default_factory=dict, max_length=32)
    observed_kinds: dict[str, str] = Field(default_factory=dict, max_length=32)
    quote_kinds: list[str] = Field(default_factory=list, max_length=32)


class Projection(Contract):
    audience: list[Perception] = Field(max_length=20)


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


class QuestionBranch(Contract):
    answer: str = Field(min_length=1, max_length=160)
    action: ActionKind


class QuestionGate(Contract):
    kind: Literal["external_fact", "player_intention"]
    missing_fact: str = Field(min_length=1, max_length=200)
    branches: tuple[QuestionBranch, QuestionBranch]


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


class ChoiceEvidence(Contract):
    source_id: str = Field(min_length=1, max_length=100)
    quote: str = Field(min_length=1, max_length=300)


class ChoicePreference(Contract):
    preferred: ActionKind
    motive_ids: list[str] = Field(min_length=1, max_length=3)
    reason: str = Field(min_length=1, max_length=300)
    continuity: Literal["new", "maintain", "revise"]
    change_basis: list[ChoiceEvidence] = Field(default_factory=list, max_length=2)


class AgentEvidence(Contract):
    source_id: str = Field(min_length=1, max_length=100)
    record_id: str = Field(min_length=1, max_length=100)
    source_message_id: str = Field(min_length=1, max_length=100)
    source_revision_id: str | None = None
    source_hash: str = Field(min_length=1, max_length=100)
    speaker_id: str = Field(min_length=1, max_length=100)
    kind: Literal["reported", "witnessed"]
    text: str = Field(min_length=1, max_length=2000)
    current_turn: bool


class PreviousIntention(Contract):
    selected: Candidate
    scene_id: str
    source_message_id: str
    source_hash: str
    source_revision_id: str | None = None
    spoken_evidence: str = Field(min_length=1, max_length=2000)


class Decision(Contract):
    choice_preference: ChoicePreference | None = None
    previous_intention: PreviousIntention | None = None
    agent_evidence: list[AgentEvidence] = Field(default_factory=list, max_length=8)
    agent_audit: list[dict[str, Any]] = Field(default_factory=list, max_length=2)
    perception_audit: dict[str, str] = Field(default_factory=dict, max_length=32)
    actor_id: str
    observation: Observation
    context_hash: str
    proposal: Proposal
    selected: Candidate
    policy_version: Literal[
        "goal-first-v1", "initiative-gated-v1", "motive-frontier-v1", "motivated-choice-v1"
    ] = "goal-first-v1"
    status: Literal["selected", "delivered", "shadow"] = "selected"
    reply_id: str | None = None
    reply_revision: str | None = None
    reply_hash: str | None = None
    spoken_evidence: str = ""
    interpretation_ids: list[str] = Field(default_factory=list, max_length=2)
    experience_ids: list[str] = Field(default_factory=list, max_length=2)
    development_ids: list[str] = Field(default_factory=list, max_length=2)
    development_status: Literal["not_yet_eligible", "available", "deferred_input_budget"] = (
        "not_yet_eligible"
    )
    selection_reasons: list[str] = Field(default_factory=list, max_length=4)
    question_gate: QuestionGate | None = None
    motive_dominance: dict[ActionKind, list[ActionKind]] = Field(default_factory=dict, max_length=4)

    motivation_policy: Literal["source-grounded-v1"] | None = None
    candidate_motives: dict[
        ActionKind, Annotated[list[ResolvedMotive], Field(min_length=1, max_length=3)]
    ] = Field(default_factory=dict, max_length=4)

    @model_validator(mode="after")
    def bounded_agent_evidence(self) -> "Decision":
        if sum(len(source.text) for source in self.agent_evidence) > 6000:
            raise ValueError("Agent evidence exceeds its combined text budget.")
        if len({source.record_id for source in self.agent_evidence}) != len(self.agent_evidence):
            raise ValueError("Agent evidence repeats a source.")
        return self

    @model_validator(mode="after")
    def complete_motive_trace(self) -> "Decision":
        offered = {candidate.kind for candidate in self.proposal.candidates}
        if self.policy_version == "motivated-choice-v1":
            if self.choice_preference is None or self.motivation_policy is None:
                raise ValueError("Semantic selection requires its preference and motive trace.")
            if self.choice_preference.preferred != self.selected.kind:
                raise ValueError("Selected intention differs from the validated preference.")
        if any(
            key not in offered or key in others or not set(others) <= offered
            for key, others in self.motive_dominance.items()
        ):
            raise ValueError("Motive comparisons must refer to distinct offered alternatives.")
        if self.policy_version == "motive-frontier-v1" and self.motivation_policy is None:
            raise ValueError("Motive-based selection requires a complete source-grounded trace.")
        if self.motivation_policy is None:
            if self.candidate_motives:
                raise ValueError("Candidate motives require their policy version.")
            return self
        if set(self.candidate_motives) != offered or self.selected.kind not in offered:
            raise ValueError("Motivation trace must cover every offered candidate.")
        return self


class Usage(Contract):
    calls: int = 0
    input_chars: int = 0
    output_chars: int = 0
    repairs: int = 0
    proposal_repairs: int = 0
    proposal_feedback: list[str] = Field(default_factory=list, max_length=2)
    status: Literal["idle", "prepared", "validated", "shadow", "failed"] = "idle"
    detail: str = ""
    memory_evictions: int = 0


class KernelState(Contract):
    schema_version: Literal[5] = 5

    @model_validator(mode="before")
    @classmethod
    def migrate_pilot_envelope(cls, value: Any) -> Any:
        if isinstance(value, dict) and value.get("schema_version") in {1, 2, 3, 4}:
            return {**value, "schema_version": 5}
        return value

    revision: int = Field(default=0, ge=0)
    settings: Settings = Field(default_factory=Settings)
    # A high-water record per actor rejects old events without an unbounded journal.
    actors: dict[str, Decision] = Field(default_factory=dict, max_length=32)
    memories: dict[str, list[MemoryEntry]] = Field(default_factory=dict, max_length=32)
    last_active: dict[str, int] = Field(default_factory=dict, max_length=32)
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
    evidence: list[SpokenEvidence] = Field(default_factory=list, max_length=20)
    heard: list[HeardSpeech] = Field(default_factory=list, max_length=12)
    agenda_evidence: list[AgendaEvidence] = Field(default_factory=list, max_length=20)
