"""Bounded transient receipts from actual wardrobe-owner application results."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from backend.engine import turn_controls
from backend.engine.clothing.profiles import load_profile
from backend.engine.clothing.schema import Region

Reason = Literal[
    "applied",
    "already_current",
    "proposal_ungrounded",
    "source_changed",
    "actor_unavailable",
    "wardrobe_rejected",
    "historical_command_owned",
]


class WardrobeOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    actor_id: str = Field(min_length=1, max_length=100)
    item_id: str | None = Field(default=None, max_length=100)
    operation: Literal["wear", "remove", "adjust", "create"]
    status: Literal["applied", "blocked"]
    reason_code: Reason
    worn: bool | None = None
    uncovered_regions: list[Region] | None = Field(default=None, max_length=7)
    source_message_id: str | None = Field(default=None, max_length=100)
    source_revision_id: str | None = Field(default=None, max_length=100)
    source_hash: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    source_role: Literal["user", "assistant"] | None = None
    control: turn_controls.Operation | None = None


def record(
    event: Any,
    plan: Any,
    change: Any,
    reason: Reason,
    *,
    actor: dict | None = None,
    item_id: str | None = None,
) -> None:
    identifier = item_id or getattr(change, "item_id", None)
    source = plan.sources.selected(change) if plan.sources else None
    captured = plan.sources.control if plan.sources else None
    control = (
        turn_controls.operation(captured, "wardrobe", actor_id=change.actor_id)
        if captured
        else None
    )
    worn = None
    regions = None
    profile = load_profile(actor.get("visual_profile")) if actor else None
    applied = reason in {"applied", "already_current"}
    if profile is not None and applied:
        entry = next((row for row in profile.worn if row.item_id == identifier), None)
        worn = entry is not None
        regions = entry.uncovered_regions if entry else None
    result = WardrobeOutcome(
        actor_id=change.actor_id,
        item_id=identifier,
        operation=getattr(change, "operation", "create"),
        status="applied" if applied else "blocked",
        reason_code=reason,
        worn=worn,
        uncovered_regions=regions,
        source_message_id=source.message_id if source else None,
        source_revision_id=source.revision_id if source else None,
        source_hash=source.content_hash if source else None,
        source_role=("user" if source.role == "user" else "assistant") if source else None,
        control=control,
    )
    event._vn_wardrobe_outcomes.append(result)


def outcome(event: Any) -> list[dict]:
    return [
        row.model_dump(exclude_none=True)
        for row in getattr(event, "_vn_wardrobe_outcomes", ())
        if isinstance(row, WardrobeOutcome)
    ]
