"""Resolve reviewer citations without asking a model to reproduce long quotations."""

from typing import Any, ClassVar, Literal

from pydantic import ConfigDict, Field, StrictBool

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


class SharedReference(Reference):
    model_config = ConfigDict(str_strip_whitespace=False)


class SharedHeardReference(HeardReference):
    model_config = ConfigDict(str_strip_whitespace=False)


class SharedReview(Contract):
    """One own-speech selector also anchors a selected agenda change."""

    model_config = ConfigDict(str_strip_whitespace=False)
    reference_wire: ClassVar[bool] = True
    review_scope: str = Field(min_length=1, max_length=100)
    matches: StrictBool
    rejections: list["ReviewRejection"] = Field(default_factory=list, max_length=8)
    evidence: list[SharedReference] = Field(default_factory=list, max_length=20)
    actions: list[SharedReference] = Field(default_factory=list, max_length=20)
    heard: list[SharedHeardReference] = Field(default_factory=list, max_length=12)
    causal_updates: list[Any] = Field(default_factory=list, max_length=20)

    @property
    def issues(self) -> list[str]:
        return [_REASONS[item.reason_code] for item in self.rejections]


class ReviewRejection(Contract):
    model_config = ConfigDict(str_strip_whitespace=False)
    reason_code: Literal[
        "intention",
        "agenda",
        "attribution",
        "agency",
        "world",
        "knowledge",
        "identity",
        "continuity",
        "inference",
        "inactive",
    ]
    actor_id: str | None = None
    passage_id: str | None = Field(default=None, min_length=1, max_length=32)


_REASONS = {
    "intention": "The expression changes the selected intention.",
    "agenda": "The spoken agenda differs from the selected change.",
    "attribution": "The expression has invalid speaker or action attribution.",
    "agency": "The narration chooses another participant's voluntary response.",
    "world": "The narration claims an unsupported world effect.",
    "knowledge": "The narration exposes unavailable knowledge.",
    "identity": "The expression contradicts the supplied identity.",
    "continuity": "The expression contradicts the retained course or current host state.",
    "inference": "The narration treats an unsupported inference as a fact.",
    "inactive": "An inactive controlled actor has a new expression.",
}


def validate_shared(review: SharedReview, scope: str, available: dict, actors: set[str]) -> None:
    if review.review_scope != scope:
        raise ChpmError("CHPM review references another prepared narration scope.")
    for item in review.rejections:
        if item.actor_id is not None and item.actor_id not in actors:
            raise ChpmError("CHPM review rejection names an unavailable actor.")
        if item.passage_id is not None and item.passage_id not in available:
            raise ChpmError("CHPM review rejection names an unavailable passage.")


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


def resolve_shared(
    review: SharedReview,
    available: dict[str, str],
    *,
    agenda_actors: set[str],
    text: str,
) -> Verdict:
    """Resolve the new producer shape without changing conflicting legacy anchors."""
    review = SharedReview.model_validate(review.model_dump())
    legacy = Review.model_validate(
        {
            **review.model_dump(exclude={"review_scope", "rejections"}),
            "issues": review.issues,
            "agenda_evidence": [
                entry.model_dump() for entry in review.evidence if entry.actor_id in agenda_actors
            ],
        }
    )
    return resolve(legacy, available, text=text)


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
