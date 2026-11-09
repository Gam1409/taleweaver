"""Bounded optional deltas for the existing post-narration extraction request."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator

from .wire_contract import operation_rules

KEY = "__scene_continuity__"
MAX_UPDATES = 12
MAX_RECORDS = 256


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Update(Model):
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


class Action(Model):
    actor_ids: list[str] = Field(min_length=1, max_length=6)
    detail: str = Field(min_length=4, max_length=400)
    evidence: str = Field(min_length=4, max_length=800)


class Evidence(Model):
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
