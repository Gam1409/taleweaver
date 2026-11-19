"""Bounded optional deltas for the existing post-narration extraction request."""

from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SerializerFunctionWrapHandler,
    StrictInt,
    model_serializer,
    model_validator,
)

from backend.core.text_evidence import WithEvidenceSpan
from backend.engine.scene_staging.schema import Placement, Posture

from .wire_contract import operation_rules

KEY = "__scene_continuity__"
MAX_UPDATES = 12
MAX_RECORDS = 256


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Update(Model, WithEvidenceSpan):
    model_config = ConfigDict(json_schema_extra=operation_rules)

    operation: Literal["record", "change", "end"]
    record_id: str = Field(default="", max_length=100)
    key: str = Field(default="", max_length=80)
    kind: Literal["environment", "process", "effect"] = "process"
    subject_id: str = Field(default="", max_length=100)
    detail: str = Field(default="", max_length=400)
    visual_detail: str = Field(default="", max_length=400)
    visibility: Literal["public", "private"] = "private"
    observers: list[str] = Field(default_factory=list, max_length=12)
    cause_id: str = Field(default="", max_length=100)
    source: Literal["narration", "scene_description"] = "narration"
    evidence: str = Field(min_length=4, max_length=800)
    review_after_minutes: StrictInt | None = Field(default=None, ge=1, le=525600)

    @model_validator(mode="after")
    def coherent(self) -> "Update":
        if self.operation == "record":
            if self.record_id or not all((self.key, self.subject_id, self.detail)):
                raise ValueError("A new fact needs key, subject and detail, without record_id.")
        elif not self.record_id or self.key or self.subject_id:
            raise ValueError("Changes reference only an existing record_id.")
        if self.operation == "change" and not self.detail:
            raise ValueError("A change needs its resulting current detail.")
        if self.source == "scene_description" and self.kind != "environment":
            raise ValueError("Authored room text establishes environment only.")
        return self


class FramePose(Model):
    """A classified visual assertion; it never grants a pose command or a state write."""

    actor_id: str = Field(min_length=1, max_length=100)
    basis: Literal["current", "completed"] = "current"
    posture: Posture | None = None
    placement: Placement | None = Field(
        default=None,
        description="Use a supplied public target ID, never an invented prop or prose label.",
    )
    clear: bool = False

    @model_validator(mode="after")
    def meaningful(self) -> "FramePose":
        if not self.clear and self.posture is None and self.placement is None:
            raise ValueError("Classified pose needs a posture, placement or explicit clear.")
        if self.posture == "unknown" or self.placement and self.placement.relation == "unknown":
            raise ValueError(
                "Unknown is not a confirmed physical state; omit the unsupported assertion."
            )
        return self


class Action(Model, WithEvidenceSpan):
    actor_ids: list[str] = Field(min_length=1, max_length=6)
    detail: str = Field(min_length=4, max_length=400)
    evidence: str = Field(min_length=4, max_length=800)
    timeframe: Literal["current", "noncurrent"] = Field(
        default="current",
        description="Noncurrent is an audit-only quotation, history, negation or hypothesis, never a depicted present physical result.",
    )
    poses: list[FramePose] | None = Field(
        default=None,
        max_length=6,
        description=(
            "Classify this very final-frame passage: [] for expression/gesture without lasting pose "
            "or placement; otherwise every asserted actor posture/placement. Null is unclassified, "
            "not confirmation. This is an observation, never command or staging authority."
        ),
    )

    @model_validator(mode="after")
    def classified_actors(self) -> "Action":
        if self.timeframe != "current" and self.poses:
            raise ValueError("Noncurrent passages cannot assert current poses.")
        if self.poses is not None and (
            any(pose.actor_id not in self.actor_ids for pose in self.poses)
            or len({pose.actor_id for pose in self.poses}) != len(self.poses)
        ):
            raise ValueError("Frame poses use distinct actors from this action's actor_ids.")
        return self

    @model_serializer(mode="wrap")
    def preserve_legacy_shape(self, handler: SerializerFunctionWrapHandler) -> dict:
        result = super().preserve_legacy_shape(handler)
        if self.poses is None:
            result.pop("poses", None)
        if self.timeframe == "current":
            result.pop("timeframe", None)
        return result


class Evidence(Model, WithEvidenceSpan):
    kind: Literal["narration", "scene_description", "unavailable"]
    source_id: str = Field(max_length=100)
    revision_id: str | None = Field(default=None, max_length=100)
    content_hash: str = Field(min_length=64, max_length=64)
    quote: str = Field(min_length=4, max_length=800)


class Record(Model):
    id: str = Field(min_length=1, max_length=100)
    key: str = Field(min_length=1, max_length=80)
    scene_id: str = Field(min_length=1, max_length=100)
    subject_id: str = Field(min_length=1, max_length=100)
    kind: Literal["environment", "process", "effect"]
    detail: str = Field(min_length=1, max_length=400)
    visual_detail: str = Field(default="", max_length=400)
    visibility: Literal["public", "private"] = "private"
    observers: list[str] = Field(default_factory=list, max_length=128)
    cause_id: str = Field(default="", max_length=100)
    status: Literal["active", "ended", "unconfirmed"] = "active"
    origin: Evidence
    latest: Evidence
    recorded_minute: StrictInt = Field(ge=0)
    updated_minute: StrictInt = Field(ge=0)
    review_at_minute: StrictInt | None = Field(default=None, ge=0)


class Ledger(Model):
    version: Literal[1] = 1
    records: dict[str, Record] = Field(default_factory=dict, max_length=MAX_RECORDS)
    frame_message_id: str = Field(default="", max_length=100)
    frame_actions: list[Action] = Field(default_factory=list, max_length=4)
    last_check: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def coherent(self) -> "Ledger":
        if any(key != row.id for key, row in self.records.items()):
            raise ValueError("Scene fact IDs disagree with their dictionary keys.")
        if any(row.cause_id and row.cause_id not in self.records for row in self.records.values()):
            raise ValueError("A scene fact references an unavailable cause.")
        return self


def candidates(value: Any) -> list[Any]:
    entries = value if isinstance(value, list) else [value]
    return [entry.model_dump() if isinstance(entry, BaseModel) else entry for entry in entries]
