"""Bind pure parsed tool calls to host-issued operations before local execution."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from backend.core.llm_tool_turn import ToolCall
from backend.engine import turn_controls
from backend.engine.chpm import tool_feedback
from backend.engine.chpm.errors import RecoverableChpmError
from backend.engine.chpm.native_tool_contracts import canonical_tool_name
from backend.engine.npc_actions import control
from backend.engine.npc_actions.contracts import Request
from backend.engine.npc_actions.preview import operation_identity


@dataclass
class Batch:
    operations: dict[str, turn_controls.Operation]
    calls: dict[str, ToolCall]
    results: list[dict]


def capture(manager: Any, tools: Any) -> dict:
    """Capture before inference; completion must never obtain a newer attempt ID."""
    return turn_controls.scope(manager, "npc_tools", observation=tools.observation)


def execute(
    manager: Any,
    tools: Any,
    calls: tuple[ToolCall, ...],
    requests: list[Any],
    errors: list[dict] | None = None,
    *,
    captured: Mapping,
) -> Batch:
    if len(calls) != len(requests) or (errors is not None and len(calls) != len(errors)):
        raise RecoverableChpmError("The parsed tool batch has inconsistent operation records.")
    if not turn_controls.bind_current(
        manager, captured, "npc_tools", observation=tools.observation
    ):
        raise RecoverableChpmError("The tool response belongs to an inactive attempt or input.")
    batch = Batch({}, {}, [])
    actor = tools.mind.genesis.scope.observer_id
    for index, (call, request) in enumerate(zip(calls, requests, strict=True)):
        actions = tools.current_actions() if isinstance(request, Request) else None
        command_id = (
            operation_identity(actions.scope, request, actions.start_index + len(actions.requests))[
                0
            ]
            if actions is not None
            else None
        )
        operation = turn_controls.operation(
            captured,
            canonical_tool_name(call.name),
            actor_id=actor,
            tool_call_id=call.id,
            command_id=command_id,
        )
        outcome = _execute(tools, request, operation, errors[index] if errors is not None else None)
        batch.operations[operation.operation_id] = operation
        batch.calls[operation.operation_id] = call
        batch.results.append(outcome)
    return batch


def legacy_calls(requests: list[Any]) -> tuple[ToolCall, ...]:
    """The older pure JSON lookup port has no provider call IDs; the host issues them."""
    return tuple(
        ToolCall(
            id="host_" + uuid4().hex,
            name=request.tool,
            arguments_raw=request.model_dump_json(exclude={"tool"}),
        )
        for request in requests
    )


def _execute(
    tools: Any, request: Any, operation: turn_controls.Operation, error: dict | None
) -> dict:
    if error is not None:
        return {
            **control.result(operation, error["status"], reason_code=error["status"]),
            # This is already bounded, host-rendered argument feedback. Preserve
            # the actionable field hint; control decisions use status/code/IDs.
            "message": error.get("message", "The tool arguments could not be validated."),
        }
    if isinstance(request, Request):
        actions = tools.current_actions()
        return (
            actions.execute(request, operation=operation)
            if actions is not None
            else control.result(operation, "unavailable_actions", reason_code="unavailable_actions")
        )
    outcome = tools.execute(request)
    return {**outcome, **operation.model_dump(exclude_none=True)}


def feedback(batch: Batch) -> tuple[tuple[ToolCall, dict], ...]:
    """Validate completeness and identity before associating any model tool response."""
    results: dict[str, dict] = {}
    for result in batch.results:
        key = result.get("operation_id") if isinstance(result, dict) else None
        if not isinstance(key, str):
            raise RecoverableChpmError("Tool results contain an invalid operation correlation.")
        expected = batch.operations.get(key)
        if key in results or expected is None or not control.same_operation(result, expected):
            raise RecoverableChpmError("Tool results contain an invalid operation correlation.")
        results[key] = result
    if results.keys() != batch.operations.keys() or batch.calls.keys() != batch.operations.keys():
        raise RecoverableChpmError("Tool results do not cover the complete issued operation batch.")
    return tuple((batch.calls[key], results[key]) for key in batch.operations)


def for_model(tool: str, result: dict) -> dict:
    """Keep correlation handles; full control bindings remain in host audit records."""
    # The request and tool envelope already identify the actor, input and tool.
    # Repeating their audit metadata for every staged step can exhaust context
    # before submission without adding evidence or authority for the model.
    repeated = (turn_controls.Operation.model_fields.keys() - {"operation_id"}) | {"event_id"}
    return {
        key: value
        for key, value in tool_feedback.for_model(tool, result).items()
        if key not in repeated and not key.startswith("diagnostic_")
    }
