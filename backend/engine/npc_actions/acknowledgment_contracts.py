"""Bounded historical command dispositions; no physical state or execution authority."""

from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SerializerFunctionWrapHandler,
    field_validator,
    model_serializer,
    model_validator,
)

from backend.engine.npc_actions.contracts import ACTION_MODELS, MAX_ACTIONS
from backend.engine.npc_actions.selected_sources import SelectionTrace

MAX_SELECTED_STEPS = 2
MAX_EXECUTION_ERRORS = 2
_EXECUTION_CODES = frozenset(
    {
        "execution_rejected",
        "declared_action_without_operation",
        "goal_operation_mismatch",
        "unexpected_operation",
        "invalid_call_envelope",
        "invalid_arguments",
        "invalid_json",
        "invalid_structure",
        "missing_requests",
        "unexpected_fields",
        "too_many_requests",
        "unclosed_requests_array",
        "unsupported_finish",
        "unavailable_actions",
        "source_coverage_mismatch",
        "ambiguous_target",
        "selected_target_mismatch",
        "unavailable_target",
        "unsupported_effect",
        "ambiguous",
    }
)


def _reason_codes() -> dict[str, str]:
    from backend.engine.npc_actions.control import MESSAGES

    return MESSAGES


Identifier = Annotated[str, Field(min_length=1, max_length=100)]


def execution_reason(code: str) -> str:
    return code if code in _EXECUTION_CODES or code in _reason_codes() else "execution_rejected"


class SelectedActionReference(BaseModel):
    """Known chosen references only; unproven operands are omitted, never certified."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    tool: Identifier
    item_id: Identifier | None = None
    recipient_id: Identifier | None = None
    target_id: Identifier | None = None
    destination_scene_id: Identifier | None = None

    @field_validator("tool")
    @classmethod
    def selected_tool(cls, value: str) -> str:
        if value not in ACTION_MODELS or value == "discard_actions":
            raise ValueError("Execution feedback requires a selected world command.")
        return value

    @model_validator(mode="after")
    def operands(self) -> "SelectedActionReference":
        fields = ACTION_MODELS[self.tool].model_fields
        supplied = {name for name in type(self).model_fields if getattr(self, name) is not None}
        if not supplied <= fields.keys():
            raise ValueError("Execution feedback includes references outside the selected command.")
        return self


class ExecutionRejection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    code: Identifier
    path: str = Field(default="/steps", max_length=100, pattern=r"^/steps(?:/[01](?:/[a-z_]+)?)?$")

    @field_validator("code")
    @classmethod
    def typed_reason(cls, value: str) -> str:
        if execution_reason(value) != value:
            raise ValueError("Execution feedback permits only typed gate refusal codes.")
        return value


class SelectedActionExecution(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    status: Literal["not_attempted", "no_effect", "rejected", "staged"]
    steps: tuple[SelectedActionReference, ...] = Field(max_length=MAX_SELECTED_STEPS)
    gate_errors: tuple[ExecutionRejection, ...] = Field(default=(), max_length=MAX_EXECUTION_ERRORS)
    source_selection: SelectionTrace | None = None
    failure_stage: Literal["interpretation", "owner_precondition"] | None = None

    @model_serializer(mode="wrap")
    def legacy_shape(self, handler: SerializerFunctionWrapHandler) -> dict:
        result: dict = handler(self)
        if self.source_selection is None:
            result.pop("source_selection", None)
        if self.failure_stage is None:
            result.pop("failure_stage", None)
        return result

    @model_validator(mode="after")
    def disposition(self) -> "SelectedActionExecution":
        if self.status == "not_attempted" and (
            self.steps or self.gate_errors or self.source_selection is not None
        ):
            raise ValueError(
                "Deliberate no action cannot carry selected steps or execution failures."
            )
        if self.status == "no_effect" and (self.steps or self.source_selection is None):
            raise ValueError("A non-effect requires its own selected source and no operations.")
        if (
            self.status in {"rejected", "staged"}
            and not self.steps
            and (self.status == "staged" or self.source_selection is None)
        ):
            raise ValueError("An execution disposition requires the actor's selected steps.")
        if self.status == "rejected" and not self.gate_errors:
            raise ValueError("Rejected execution requires its typed gate reason.")
        if (
            self.source_selection is not None
            and self.status == "no_effect"
            and (
                not self.source_selection.resolutions
                or any(row.disposition != "no_effect" for row in self.source_selection.resolutions)
            )
        ):
            raise ValueError("A non-effect disposition must account for every selected phrase.")
        return self


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
    execution: SelectedActionExecution | None = None

    @model_serializer(mode="wrap")
    def legacy_shape(self, handler: SerializerFunctionWrapHandler) -> dict:
        result: dict = handler(self)
        if self.execution is None:
            result.pop("execution", None)
        return result

    @model_validator(mode="after")
    def unique_operations(self) -> "PublicationAcknowledgment":
        if len({row.operation_id for row in self.operations}) != len(self.operations):
            raise ValueError("Publication feedback repeats an operation identity.")
        if self.execution is not None and (
            (self.execution.status != "staged" and self.operations)
            or (
                self.execution.status == "staged"
                and len(self.operations) != len(self.execution.steps)
            )
        ):
            raise ValueError("Execution feedback and publication dispositions disagree.")
        self._source_operations()
        return self

    def _source_operations(self) -> None:
        if self.execution is None or self.execution.source_selection is None:
            return
        trace = self.execution.source_selection
        if trace.selection.control.attempt_id != self.attempt_id:
            raise ValueError("Publication and selection must belong to the same attempt.")
        if self.execution.status != "staged":
            return
        actions = [action for group in trace.resolutions for action in group.actions]
        if [(row.operation_id, row.tool) for row in actions] != [
            (row.operation_id, row.tool) for row in self.operations
        ]:
            raise ValueError("Published operations must retain the selected source order.")
        for step, operation in zip(self.execution.steps, self.operations, strict=True):
            if any(
                getattr(step, key) != getattr(operation, key) for key in type(step).model_fields
            ):
                raise ValueError("Publication feedback cannot substitute selected operands.")
