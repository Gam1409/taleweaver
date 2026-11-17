"""Optional physical layout and wear provenance inside the existing visual profile."""

from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SerializerFunctionWrapHandler,
    field_validator,
    model_serializer,
    model_validator,
)

from backend.core.text_evidence import WithEvidenceSpan

BodySlot = Literal["vaginal", "anal", "uterine", "penile"]
BODY_SLOT_KEYS: dict[BodySlot, str] = {
    "vaginal": "BodyVaginal",
    "anal": "BodyAnal",
    "uterine": "BodyUterine",
    "penile": "BodyPenile",
}


class BodyLayout(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    form: Literal["humanoid", "non_humanoid", "unknown"] = "unknown"
    silhouette: Literal["male", "female", "neutral"] | None = None
    attachment_slots: list[BodySlot] | None = Field(
        default=None,
        max_length=4,
        description="Explicit available regions. Null is unassessed; [] explicitly excludes them. Never derive anatomy from gender.",
    )

    @field_validator("attachment_slots")
    @classmethod
    def unique(cls, value: list[BodySlot] | None) -> list[BodySlot] | None:
        if value is not None and len(value) != len(set(value)):
            raise ValueError("Body regions must be unique.")
        return value


class WearCommandProof(BaseModel):
    """Host-issued command binding; absence of an imported input keeps it historical."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    command_id: str = Field(min_length=1, max_length=100)
    actor_id: str = Field(min_length=1, max_length=100)
    item_id: str = Field(min_length=1, max_length=100)
    input_id: str | None = Field(min_length=1, max_length=100)
    input_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    input_revision: str | None = Field(default=None, min_length=1, max_length=100)
    request_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    operation: Literal["wear_item", "adjust_clothing", "attach_item"]


class WearSource(WithEvidenceSpan):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    request_id: str | None = Field(default=None, min_length=1, max_length=100)
    source_message_id: str | None = Field(default=None, max_length=100)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    evidence: str = Field(default="", max_length=800)
    source_role: Literal["assistant", "user", "command"] = "assistant"
    command: WearCommandProof | None = None

    @model_validator(mode="after")
    def coherent(self) -> "WearSource":
        if self.source_role != "command":
            if len(self.evidence) < 4 or self.command is not None:
                raise ValueError("Narrated wear requires a real quote without command provenance.")
            return self
        proof = self.command
        if proof is None or self.evidence or self.evidence_span is not None:
            raise ValueError("Command wear requires its host proof, without a narration quote.")
        if (
            self.content_hash != proof.request_hash
            or self.request_id != proof.input_id
            or self.source_message_id != proof.input_id
        ):
            raise ValueError("Command wear provenance must match its bound input and request.")
        return self

    @classmethod
    def from_command(cls, proof: WearCommandProof) -> "WearSource":
        if proof.input_id is None:
            raise ValueError("A new wear command requires its bound current input.")
        return cls(
            request_id=proof.input_id,
            source_message_id=proof.input_id,
            content_hash=proof.request_hash,
            source_role="command",
            command=proof,
        )

    @model_serializer(mode="wrap")
    def legacy_source(self, handler: SerializerFunctionWrapHandler) -> dict:
        result: dict = handler(self)
        if self.evidence_span is None:
            result.pop("evidence_span", None)
        if self.source_role == "assistant":
            result.pop("source_role", None)
        if self.command is None:
            result.pop("command", None)
        if self.source_role == "command":
            result.pop("evidence", None)
        return result
