"""Resolve reviewer citations without asking a model to reproduce long quotations."""

import re

from pydantic import Field, StrictBool

from backend.engine.chpm.kernel import ChpmError
from backend.engine.chpm.schema import Contract, Verdict


class Reference(Contract):
    actor_id: str
    passage_id: str | None = Field(default=None, min_length=1, max_length=32)


class HeardReference(Reference):
    speaker_id: str


class Review(Contract):
    matches: StrictBool
    issues: list[str] = Field(default_factory=list, max_length=8)
    evidence: list[Reference] = Field(default_factory=list, max_length=20)
    heard: list[HeardReference] = Field(default_factory=list, max_length=12)
    agenda_evidence: list[Reference] = Field(default_factory=list, max_length=20)


def index(text: str) -> dict[str, str]:
    # Segmentation assigns references, never speaker identity or factual status.
    pieces = re.findall(r'[^\n]+?(?:[.!?。！？]["”»]?(?=\s|$)|(?=\n)|$)', text)
    chunks = [
        piece[start : start + 600].strip()
        for piece in pieces
        for start in range(0, len(piece), 600)
    ]
    return {f"p{number}": chunk for number, chunk in enumerate(chunks) if chunk}


def resolve(review: Review, available: dict[str, str]) -> Verdict:
    return Verdict.model_validate(
        {
            "matches": review.matches,
            "issues": review.issues,
            **{
                field: [_resolve_entry(entry, available) for entry in getattr(review, field)]
                for field in ("evidence", "heard", "agenda_evidence")
            },
        }
    )


def _resolve_entry(entry: Reference, available: dict[str, str]) -> dict:
    quote = ""
    if entry.passage_id is not None:
        quote = available.get(entry.passage_id, "")
        if not quote:
            raise ChpmError("CHPM reviewer supplied an unknown passage reference.")
    return {**entry.model_dump(exclude={"passage_id"}), "quote": quote}
