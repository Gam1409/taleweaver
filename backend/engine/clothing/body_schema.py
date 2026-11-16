"""Optional physical layout and wear provenance inside the existing visual profile."""

from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SerializerFunctionWrapHandler,
    field_validator,
    model_serializer,
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


class WearSource(WithEvidenceSpan):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    request_id: str | None = Field(default=None, min_length=1, max_length=100)
    source_message_id: str | None = Field(default=None, max_length=100)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    evidence: str = Field(min_length=4, max_length=800)
    source_role: Literal["assistant", "user"] = "assistant"

    @model_serializer(mode="wrap")
    def legacy_source(self, handler: SerializerFunctionWrapHandler) -> dict:
        result: dict = handler(self)
        if self.evidence_span is None:
            result.pop("evidence_span", None)
        if self.source_role == "assistant":
            result.pop("source_role", None)
        return result
