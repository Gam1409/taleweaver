"""Resolve reviewer citations without asking a model to reproduce long quotations."""

from typing import Any

from pydantic import Field, StrictBool

from backend.core import text_passages
from backend.engine.chpm.kernel import ChpmError
from backend.engine.chpm.schema import Contract, Verdict


class Reference(Contract):
    actor_id: str
    passage_id: str | None = Field(default=None, min_length=1, max_length=32)


class HeardReference(Reference):
    speaker_id: str
    origin_id: str | None = Field(default=None, min_length=1, max_length=80)


class Review(Contract):
    matches: StrictBool
    issues: list[str] = Field(default_factory=list, max_length=8)
    evidence: list[Reference] = Field(default_factory=list, max_length=20)
    actions: list[Reference] = Field(default_factory=list, max_length=20)
    heard: list[HeardReference] = Field(default_factory=list, max_length=12)
    agenda_evidence: list[Reference] = Field(default_factory=list, max_length=20)
    causal_updates: list[Any] = Field(default_factory=list, max_length=20)


def index(text: str) -> dict[str, str]:
    return text_passages.index(text)


def resolve(review: Review, available: dict[str, str], *, text: str | None = None) -> Verdict:
    occurrences = text_passages.spans(text) if text is not None else {}
    return Verdict.model_validate(
        {
            "matches": review.matches,
            "issues": review.issues,
            "causal_updates": review.causal_updates,
            **{
                field: [
                    _resolve_entry(
                        entry,
                        available,
                        occurrences.get(entry.passage_id or "") if field == "actions" else None,
                    )
                    for entry in getattr(review, field)
                ]
                for field in ("evidence", "actions", "heard", "agenda_evidence")
            },
        }
    )


def _resolve_entry(
    entry: Reference, available: dict[str, str], occurrence: text_passages.Passage | None = None
) -> dict:
    quote = ""
    if entry.passage_id is not None:
        quote = available.get(entry.passage_id, "")
        if not quote:
            raise ChpmError("CHPM reviewer supplied an unknown passage reference.")
    result = {**entry.model_dump(exclude={"passage_id"}), "quote": quote}
    if occurrence is not None:
        if occurrence.text != quote:
            raise ChpmError("CHPM reviewer passage differs from its source occurrence.")
        result["evidence_span"] = {"start": occurrence.start, "end": occurrence.end}
    return result
