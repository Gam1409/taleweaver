"""Portable inputs and outputs for the dialogue comparison harness."""

from typing import Annotated, Literal

from pydantic import Field, model_validator

from backend.engine.chpm.schema import Contract
from backend.engine.personality.profile import PersonalityProfile

Arm = Literal["baseline", "chpm"]


class HistoryLine(Contract):
    speaker: Literal["npc", "@player"]
    text: str = Field(min_length=1, max_length=2000)


class SeedAgenda(Contract):
    history_index: int = Field(ge=0, le=79, strict=True)
    kind: Literal["goal", "commitment"] = "commitment"
    text: str = Field(min_length=1, max_length=300)


class Case(Contract):
    id: str
    language: Literal["English", "Russian"]
    name: str
    character: str
    goal: str
    personality: PersonalityProfile = Field(default_factory=PersonalityProfile)
    scene: str
    history: list[HistoryLine] = Field(default_factory=list, max_length=80)
    agenda: list[SeedAgenda] = Field(default_factory=list, max_length=8)
    message: str
    rubric: str

    @model_validator(mode="after")
    def owned_agenda_sources(self) -> "Case":
        if any(
            item.history_index >= len(self.history)
            or self.history[item.history_index].speaker != "npc"
            for item in self.agenda
        ):
            raise ValueError("Fixture agenda must cite an existing NPC utterance.")
        return self


class Call(Contract):
    phase: str
    role: str
    model: str
    provider: str
    elapsed_ms: float = 0
    input_chars: int
    output_chars: int = 0
    returned_text: str = ""
    text_truncated: bool = False
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    status: Literal["ok", "failed"] = "failed"
    context_audit: dict = Field(default_factory=dict)


class Result(Contract):
    pair_id: str
    case_id: str
    case_hash: str
    repetition: int
    arm: Arm
    status: Literal["ok", "failed"]
    response: str = ""
    error_type: str = ""
    error_detail: str = ""
    elapsed_ms: float
    calls: list[Call] = Field(default_factory=list)
    trace: dict = Field(default_factory=dict)


Score = Annotated[int, Field(ge=0, le=4, strict=True)]


class Rating(Contract):
    pair_id: str
    response_hashes: dict[str, str]
    preferred: Literal["A", "B", "tie", "unrateable"] | None = None
    reason: str = Field(default="", max_length=2000)
    # Null means unreviewed, not a score of zero.
    voice: dict[Literal["A", "B"], Score | None]
    initiative: dict[Literal["A", "B"], Score | None]
    relevant_questions: dict[Literal["A", "B"], Score | None]
    continuity: dict[Literal["A", "B"], Score | None]

    @model_validator(mode="after")
    def paired_labels(self) -> "Rating":
        mappings = (
            self.response_hashes,
            self.voice,
            self.initiative,
            self.relevant_questions,
            self.continuity,
        )
        if any(set(values) != {"A", "B"} for values in mappings):
            raise ValueError("Each rating dimension must contain exactly A and B.")
        return self
