"""Bounded owner receipts for exact narration occurrences, without private rule details."""

from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SerializerFunctionWrapHandler,
    StringConstraints,
    model_serializer,
)

from backend.core.text_evidence import EvidenceSpan, unique_span

Status = Literal["applied", "blocked", "unconfirmed"]


class MovementOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    actor_id: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
    status: Status
    evidence: str = Field(min_length=1, max_length=2000)
    evidence_span: EvidenceSpan


class WithMovementOutcomes(BaseModel):
    movement_outcomes: tuple[MovementOutcome, ...] = Field(default=(), max_length=8)
    action_span: EvidenceSpan | None = None

    @model_serializer(mode="wrap")
    def legacy_movement_shape(self, handler: SerializerFunctionWrapHandler) -> dict:
        result: dict = handler(self)
        if not self.movement_outcomes:
            result.pop("movement_outcomes", None)
        if self.action_span is None:
            result.pop("action_span", None)
        return result


class MovementBlockedError(ValueError):
    """A known world rule denied a source-valid, completed movement proposal."""


def receipt(raw: Any, narration: str, status: Status) -> MovementOutcome | None:
    if not isinstance(raw, dict):
        return None
    try:
        quote = raw.get("evidence")
        if not isinstance(quote, str):
            return None
        supplied = raw.get("evidence_span")
        span = unique_span(
            narration, quote, EvidenceSpan.model_validate(supplied) if supplied else None
        )
        if span is None:
            return None
        return MovementOutcome(
            actor_id=raw["actor_id"], status=status, evidence=quote, evidence_span=span
        )
    except (KeyError, ValueError):
        return None


def for_quote(
    entries: tuple[MovementOutcome, ...],
    narration: str,
    quote: str,
    actor: str | None,
    supplied: EvidenceSpan | None = None,
) -> tuple[MovementOutcome, ...]:
    span = unique_span(narration, quote, supplied)
    if span is None:
        return ()
    return tuple(
        MovementOutcome(
            actor_id=entry.actor_id,
            status=entry.status,
            evidence=narration[
                max(span.start, entry.evidence_span.start) : min(span.end, entry.evidence_span.end)
            ],
            evidence_span=EvidenceSpan(
                start=max(span.start, entry.evidence_span.start),
                end=min(span.end, entry.evidence_span.end),
            ),
        )
        for entry in entries
        if (actor is None or entry.actor_id == actor)
        and entry.evidence_span.matches(narration, entry.evidence)
        and overlaps(entry, quote, span)
    )


def overlaps(entry: MovementOutcome, quote: str, span: EvidenceSpan) -> bool:
    start = max(span.start, entry.evidence_span.start)
    end = min(span.end, entry.evidence_span.end)
    return (
        span.end - span.start == len(quote)
        and start < end
        and quote[start - span.start : end - span.start]
        == entry.evidence[start - entry.evidence_span.start : end - entry.evidence_span.start]
    )


def descriptor(value: WithMovementOutcomes) -> dict:
    if not value.movement_outcomes:
        return {}
    return {
        "movement_outcomes": [entry.model_dump(mode="json") for entry in value.movement_outcomes],
        "movement_outcome_scope": "Only the cited movement; other narrated effects are not certified. Unconfirmed is not a fictional failure.",
    }


def evidence_size(text: str, value: WithMovementOutcomes) -> int:
    # Account for qualification as well as the unchanged quoted text in tool handoffs.
    import json

    return len(text) + len(json.dumps(descriptor(value), ensure_ascii=False)) - 2
