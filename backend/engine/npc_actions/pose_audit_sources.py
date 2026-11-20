"""Bounded transient pose classifications and source identity across one prose repair."""

from dataclasses import dataclass, field
from hashlib import sha256
from typing import Any

from pydantic import BaseModel

from backend.core.text_passages import spans
from backend.engine.chpm.errors import ChpmError
from backend.engine.scene_continuity.schema import Action

REASONS = frozenset(
    {
        "pose_classification_required",
        "pose_classification_invalid",
        "pose_source_unavailable",
        "pose_target_unavailable",
        "pose_state_mismatch",
        "pose_operation_unavailable",
    }
)


class PoseAuditUnavailableError(ChpmError):
    """The required current owner/review binding cannot establish a physical result."""


@dataclass(frozen=True)
class Pending:
    control: dict
    source_hash: str
    state_hash: str
    review_scope: str | None
    sources: dict[tuple[str, str], str] = field(default_factory=dict)
    approved: list[Action] = field(default_factory=list)


def digest(text: str) -> str:
    return sha256(text.encode()).hexdigest()


def read(raw: Any) -> tuple[dict, Action | None]:
    body = raw.model_dump() if isinstance(raw, BaseModel) else raw
    if not isinstance(body, dict):
        return {}, None
    try:
        return body, Action.model_validate(body)
    except ValueError:
        return body, None


def _resolved(issue: dict, actions: list[Action]) -> bool:
    return bool(actions) and (
        issue["reason_code"] in {"pose_classification_required", "pose_classification_invalid"}
        or all(issue["actor_id"] not in action.actor_ids for action in actions)
        or all(action.timeframe == "noncurrent" for action in actions)
    )


def _repeated_issue(
    previous: Pending, issue: dict, narration: str, actions: list[Action], current: dict
) -> dict | None:
    if issue.get("reason_code") not in REASONS:
        return None
    actor, source_hash = issue.get("actor_id"), issue.get("source_passage_hash")
    if not isinstance(actor, str) or not isinstance(source_hash, str):
        raise PoseAuditUnavailableError("The rejected physical source is not bound to its actor.")
    quote = previous.sources.get((actor, source_hash))
    if not isinstance(quote, str):
        raise PoseAuditUnavailableError("The rejected physical source cannot be rechecked.")
    # A repair can move or repeat the original sentence. Each surviving
    # occurrence needs its own current classification before the issue is cleared.
    passages = spans(narration)
    classified = [
        action
        for action in actions
        if action.evidence_span is not None
        and action.evidence_span.matches(narration, action.evidence)
        and action.poses is not None
    ]
    start = narration.find(quote)
    while start >= 0 and quote:
        covering = [
            action
            for action in classified
            if action.evidence_span is not None
            and action.evidence_span.start <= start
            and action.evidence_span.end >= start + len(quote)
        ]
        if not _resolved(issue, covering):
            anchor = next(
                (key for key, row in passages.items() if row.start <= start < row.end), None
            )
            if anchor is None:
                raise PoseAuditUnavailableError(
                    "The repeated physical source has no current passage."
                )
            return {
                **issue,
                "passage_id": anchor,
                "expected_public_result": {"current_owner_pose": current.get(actor, {})},
            }
        start = narration.find(quote, start + 1)
    return None


def repeat(
    previous: Pending | None, retry: Any, narration: str, rows: list, current: dict
) -> list[dict]:
    if retry is None:
        return []
    if not isinstance(previous, Pending) or previous.review_scope != retry.proof.review_scope:
        if any(issue.get("reason_code") in REASONS for issue in retry.failures):
            raise PoseAuditUnavailableError(
                "The original pose audit source is unavailable for retry."
            )
        return []
    actions = [action for raw in rows if (action := read(raw)[1]) is not None]
    return [
        conflict
        for issue in retry.failures
        if (conflict := _repeated_issue(previous, issue, narration, actions, current)) is not None
    ]
