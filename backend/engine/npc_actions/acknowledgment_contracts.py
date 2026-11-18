"""Bounded historical command dispositions; no physical state or execution authority."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from backend.engine.npc_actions.contracts import ACTION_MODELS, MAX_ACTIONS


def _reason_codes() -> dict[str, str]:
    from backend.engine.npc_actions.control import MESSAGES

    return MESSAGES


Identifier = Annotated[str, Field(min_length=1, max_length=100)]


class OperationAcknowledgment(BaseModel):
    """Only operation identity and disposition; no effects, diagnostics or other plans."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    operation_id: Identifier
    tool: Identifier
    status: Literal["applied", "attempted", "blocked", "skipped_dependency", "stale"]
    reason_code: Identifier | None = None
    item_id: Identifier | None = None
    recipient_id: Identifier | None = None
    target_id: Identifier | None = None
    destination_scene_id: Identifier | None = None

    @field_validator("tool")
    @classmethod
    def published_tool(cls, value: str) -> str:
        if value not in ACTION_MODELS or value == "discard_actions":
            raise ValueError("Publication feedback requires an executable command tool.")
        return value

    @model_validator(mode="after")
    def final_status(self) -> "OperationAcknowledgment":
        if self.reason_code is not None and (
            self.reason_code not in _reason_codes() or self.status in {"applied", "attempted"}
        ):
            raise ValueError("Publication feedback permits only typed refusal codes on failures.")
        if (self.status == "attempted" and self.tool != "interact") or (
            self.status == "applied" and self.tool == "interact"
        ):
            raise ValueError("An interaction attempt does not certify the target's response.")
        return self


class PublicationAcknowledgment(BaseModel):
    """One latest decision's own result references, not an independently replayable receipt."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    attempt_id: Identifier
    operations: tuple[OperationAcknowledgment, ...] = Field(max_length=MAX_ACTIONS)

    @model_validator(mode="after")
    def unique_operations(self) -> "PublicationAcknowledgment":
        if len({row.operation_id for row in self.operations}) != len(self.operations):
            raise ValueError("Publication feedback repeats an operation identity.")
        return self
