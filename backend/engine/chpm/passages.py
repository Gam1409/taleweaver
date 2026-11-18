"""Resolve reviewer citations without asking a model to reproduce long quotations."""

from typing import Any, ClassVar, Literal

from pydantic import ConfigDict, Field, StrictBool, model_validator

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

    @model_validator(mode="before")
    @classmethod
    def rejected_expression_fields(cls, value: Any) -> Any:
        return rejected_candidate(value) if isinstance(value, dict) else value

    @model_validator(mode="after")
    def no_rejected_effects(self) -> "SharedReview":
        # A negative verdict can request repair but never grant speech, hearing or memory effects.
        if not self.matches:
            for field in _SUCCESS_FIELDS:
                setattr(self, field, [])
        return self

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


class CompletedChange(Contract):
    """A reviewer's claimed completion, never a command or a state update."""

    model_config = ConfigDict(str_strip_whitespace=False)
    actor_id: str = Field(min_length=1, max_length=100)
    passage_id: str = Field(min_length=1, max_length=32)
    operation_id: str = Field(min_length=1, max_length=100)
    tool: str = Field(min_length=1, max_length=100)
    target_id: str = Field(min_length=1, max_length=100)
    recipient_id: str | None = Field(default=None, min_length=1, max_length=100)
    posture: str | None = Field(default=None, min_length=1, max_length=120)
    uncovered_regions: list[str] | None = Field(default=None, max_length=7)


class ReceiptReview(SharedReview):
    """Controlled publication requires explicit, separately checked completion coverage."""

    completed_changes_wire: ClassVar[bool] = True
    completed_changes: list[CompletedChange] | None = Field(default=None, max_length=320)

    @model_validator(mode="before")
    @classmethod
    def discard_rejected_claims(cls, value: Any) -> Any:
        if isinstance(value, dict) and value.get("matches") is False and value.get("rejections"):
            return {**value, "completed_changes": []}
        return value


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

_SUCCESS_FIELDS = ("evidence", "actions", "heard", "causal_updates")


def rejected_candidate(candidate: dict) -> dict:
    """Preserve typed refusal data; unused positive fields cannot obstruct a valid rejection."""
    rejections = candidate.get("rejections")
    if candidate.get("matches") is not False or not isinstance(rejections, list) or not rejections:
        return candidate
    # The complete outer DTO and current-ID validation still check every rejection and the scope.
    return {**candidate, **{field: [] for field in _SUCCESS_FIELDS if field in candidate}}


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
    review = type(review).model_validate(review.model_dump())
    legacy = Review.model_validate(
        {
            **review.model_dump(exclude={"review_scope", "rejections", "completed_changes"}),
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
