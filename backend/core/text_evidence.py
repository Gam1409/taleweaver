"""Optional exact occurrence metadata; legacy provenance keeps its serialized shape."""

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SerializerFunctionWrapHandler,
    StrictInt,
    model_serializer,
    model_validator,
)
from pydantic.json_schema import SkipJsonSchema


class EvidenceSpan(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    start: StrictInt = Field(ge=0)
    end: StrictInt = Field(gt=0)

    @model_validator(mode="after")
    def ordered(self) -> "EvidenceSpan":
        if self.end <= self.start:
            raise ValueError("Evidence span must have positive length.")
        return self

    def matches(self, text: str, quote: str) -> bool:
        return 0 <= self.start < self.end <= len(text) and text[self.start : self.end] == quote


class WithEvidenceSpan(BaseModel):
    evidence_span: SkipJsonSchema[EvidenceSpan | None] = None

    @model_serializer(mode="wrap")
    def preserve_legacy_shape(self, handler: SerializerFunctionWrapHandler) -> dict:
        result: dict = handler(self)
        if self.evidence_span is None:
            result.pop("evidence_span", None)
        return result


def require_span(text: str, quote: str, span: EvidenceSpan | None) -> None:
    if span is not None and not span.matches(text, quote):
        raise ValueError("Evidence span does not match its original source occurrence.")


def unique_span(text: str, quote: str, span: EvidenceSpan | None) -> EvidenceSpan | None:
    """Use an exact selected occurrence, or a unique legacy literal including overlaps."""
    if span is not None:
        require_span(text, quote, span)
        return span
    start = text.find(quote)
    if not quote or start < 0 or text.find(quote, start + 1) >= 0:
        return None
    return EvidenceSpan(start=start, end=start + len(quote))
