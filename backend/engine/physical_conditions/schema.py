"""Small operation vocabulary; omission never resolves an existing condition."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator

from backend.core.text_evidence import WithEvidenceSpan
from backend.engine.clothing.schema import Region
from backend.engine.physical_conditions.wire_contract import operation_rules

KEY = "__physical_conditions__"
MAX_PROPOSALS = 12
MAX_ACTIVE = 512
MAX_RESOLVED = 64
MAX_EVENTS = 128
Kind = Literal["injury", "contamination", "fluid", "pain", "other"]
Status = Literal["active", "treated", "reduced", "resolved"]
Operation = Literal["record", "change", "treat", "reduce", "clean", "heal", "remove"]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ConditionProposal(Model, WithEvidenceSpan):
    model_config = ConfigDict(json_schema_extra=operation_rules)

    operation: Operation
    condition_id: str | None = Field(default=None, max_length=100)
    target_id: str | None = Field(default=None, max_length=100)
    kind: Kind | None = None
    part: str = Field(default="", max_length=80)
    detail: str = Field(default="", max_length=320)
    visibility: Literal["public", "private"] | None = None
    visual_detail: str = Field(default="", max_length=320)
    visual_region: Region | None = None
    evidence: str = Field(min_length=4, max_length=600)

    @model_validator(mode="after")
    def coherent(self) -> "ConditionProposal":
        if self.operation == "record":
            if (
                not self.target_id
                or not self.kind
                or not self.part
                or not self.detail
                or self.condition_id
            ):
                raise ValueError(
                    "Recording requires target, kind, part and detail, without an existing condition ID."
                )
        elif not self.condition_id or self.target_id or self.kind or self.part:
            raise ValueError(
                "An update references only its existing condition ID, not a new target or body part."
            )
        if self.operation == "change" and not self.detail:
            raise ValueError("A description change requires the new detail.")
        return self


class Source(Model, WithEvidenceSpan):
    kind: Literal["narration", "manual", "unavailable"]
    message_id: str | None = Field(default=None, max_length=100)
    content_hash: str = Field(default="", max_length=64)
    quote: str = Field(min_length=1, max_length=600)

    @model_validator(mode="after")
    def coherent(self) -> "Source":
        if self.kind == "narration" and (not self.message_id or len(self.content_hash) != 64):
            raise ValueError("Narration sources require a saved message ID and content hash.")
        return self


class Condition(Model):
    id: str = Field(min_length=1, max_length=100)
    target_id: str = Field(min_length=1, max_length=100)
    kind: Kind
    part: str = Field(min_length=1, max_length=80)
    detail: str = Field(min_length=1, max_length=320)
    status: Status = "active"
    visibility: Literal["public", "private"] = "private"
    visual_detail: str = Field(default="", max_length=320)
    visual_region: Region | None = None
    origin: Source
    latest: Source
    updated_revision: StrictInt = Field(ge=0)
    first_recorded_minute: StrictInt | None = Field(default=None, ge=0)
    last_changed_minute: StrictInt | None = Field(default=None, ge=0)


class Event(Model):
    condition_id: str
    operation: Operation
    revision: StrictInt = Field(ge=1)
    source: Source


class Ledger(Model):
    version: Literal[1] = 1
    revision: StrictInt = Field(default=0, ge=0)
    conditions: dict[str, Condition] = Field(
        default_factory=dict, max_length=MAX_ACTIVE + MAX_RESOLVED
    )
    events: list[Event] = Field(default_factory=list, max_length=MAX_EVENTS)
    archived_resolved: StrictInt = Field(default=0, ge=0)
    archived_events: StrictInt = Field(default=0, ge=0)
    last_check: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def coherent(self) -> "Ledger":
        if any(key != value.id for key, value in self.conditions.items()):
            raise ValueError("Condition IDs and dictionary keys disagree.")
        if sum(row.status != "resolved" for row in self.conditions.values()) > MAX_ACTIVE:
            raise ValueError("Too many active conditions.")
        return self


def candidate_values(value: Any) -> list[Any]:
    """Keep invalid optional candidates for auditing without losing valid item actions."""
    entries = value if isinstance(value, list) else [value]
    return [
        entry.model_dump() if isinstance(entry, ConditionProposal) else entry for entry in entries
    ]
