"""Translate an NPC's selected physical steps into one ordinary, atomically staged command batch."""

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from backend.core.llm_tool_turn import ToolCall
from backend.engine import turn_controls
from backend.engine.chpm import agent_native, inference, parallel_budget
from backend.engine.chpm.agent_tools import Tools
from backend.engine.chpm.errors import StaleControlError
from backend.engine.chpm.native_tool_contracts import NativeToolArgumentError, parse_call
from backend.engine.chpm.notebook_tools import result_summary
from backend.engine.chpm.schema import Settings, Usage
from backend.engine.npc_actions.acknowledgment_contracts import (
    MAX_EXECUTION_ERRORS,
    MAX_SELECTED_STEPS,
    ExecutionRejection,
    SelectedActionExecution,
    SelectedActionReference,
    execution_reason,
)
from backend.engine.npc_actions.contracts import ACTION_MODELS, Adjust, Request
from backend.engine.npc_actions.feedback import summarize
from backend.engine.npc_actions.preview import Draft, Scope, SelectedStepRejectedError
from backend.engine.npc_actions.selected_sources import SelectionTrace
from backend.engine.npc_actions.tool_schema import definitions

INSTRUCTION = (
    "You already chose the ordered physical steps below for your own character. "
    "Call each corresponding world function with its arguments, in that order, in this response. "
    "The tool name is the function name; omit tool from arguments. "
    "Use the provided IDs. The host checks feasibility and publishes results later."
)


@dataclass(frozen=True)
class ExecutionGateError(Exception):
    code: str
    path: str = "/steps"

    def feedback(self) -> dict[str, str]:
        return {"code": self.code, "path": self.path}


def _bound(manager: Any, tools: Tools, captured: Mapping, draft: Draft | None) -> Draft:
    if (
        draft is None
        or tools.current_actions() is not draft
        or manager.game_id != draft.scope.session_id
        or manager.state.current_scene_id != draft.scope.scene_id
        or not turn_controls.bind_current(
            manager, captured, "npc_tools", observation=tools.observation
        )
        or not turn_controls.bind_current(
            manager, draft.scope.control, "npc_command_preview", observation=tools.observation
        )
    ):
        raise StaleControlError("Physical execution belongs to another actor, input or attempt.")
    if (
        draft.approved
        or draft.requests
        or draft.receipts
        or draft.operations
        or draft.published_results is not None
    ):
        # A previous writer or replay already touched this draft. Never adopt or clear its work.
        raise StaleControlError(
            "unexpected_operation: physical execution needs an open, empty draft."
        )
    return draft


def _mismatch(expected: Request, proposed: Request, index: int) -> str | None:
    if type(proposed) is not type(expected):
        return f"/steps/{index}/tool"
    for field in type(expected).model_fields:
        chosen, actual = getattr(expected, field), getattr(proposed, field)
        if isinstance(expected, Adjust) and field == "uncovered_regions":
            chosen, actual = set(chosen), set(actual)
        if chosen != actual:
            return f"/steps/{index}/{field}"
    return None


def _match(calls: tuple[ToolCall, ...], seen_ids: set[str], steps: Sequence[Request]) -> None:
    if not calls:
        raise ExecutionGateError("declared_action_without_operation")
    valid = agent_native._valid_envelope(calls, seen_ids)
    # IDs on a rejected batch cannot be reassigned to a different operation during repair.
    seen_ids.update(call.id for call in calls if 0 < len(call.id) <= 128)
    if not valid:
        raise ExecutionGateError("invalid_call_envelope")
    if len(calls) != len(steps):
        raise ExecutionGateError("goal_operation_mismatch")
    for index, (call, step) in enumerate(zip(calls, steps, strict=True)):
        if call.name != step.tool:
            raise ExecutionGateError("goal_operation_mismatch", f"/steps/{index}/tool")
        try:
            parsed = parse_call(call.name, call.arguments_raw)
        except NativeToolArgumentError as exc:
            raise ExecutionGateError(exc.code, f"/steps/{index}") from exc
        if not isinstance(parsed, Request):
            raise ExecutionGateError("unexpected_operation", f"/steps/{index}/tool")
        difference = _mismatch(step, parsed, index)
        if difference:
            raise ExecutionGateError("goal_operation_mismatch", difference)


def _repair_available(manager: Any, settings: Settings, usage: Usage) -> bool:
    turn = getattr(manager, "_chpm_turn", None)
    other_actors = max(0, len(getattr(turn, "names", ())) - len(getattr(turn, "decisions", {})) - 1)
    normal = parallel_budget.remaining(other_actors * (1 + settings.agent_steps))
    # One shared proposal repair, without taking the remaining actors' or narrator review's calls.
    return (
        not usage.proposal_repairs and usage.calls + 1 + normal + 3 <= settings.max_calls_per_turn
    )


def _selected_references(scope: Scope, request: Request) -> SelectedActionReference:
    values = request.model_dump(
        include={"tool", "item_id", "recipient_id", "target_id", "destination_scene_id"},
        exclude_none=True,
    )
    allowed = {
        "item_id": scope.accessible_ids & scope.possessions.items.keys(),
        "target_id": scope.accessible_ids,
        "recipient_id": scope.accessible_ids & (scope.actors.keys() | {"@player"}),
        "destination_scene_id": scope.destinations,
    }
    return SelectedActionReference.model_validate(
        {key: value for key, value in values.items() if key == "tool" or value in allowed[key]}
    )


def _audit(
    draft: Draft,
    protocol: str,
    status: Literal["not_attempted", "no_effect", "rejected", "staged"],
    failures: list[ExecutionGateError],
    repaired: bool,
    steps: Sequence[Request],
    *,
    source_selection: SelectionTrace | None = None,
    failure_stage: Literal["interpretation", "owner_precondition"] | None = None,
) -> list[dict]:
    errors = tuple(
        ExecutionRejection(code=execution_reason(failure.code), path=failure.path)
        for failure in failures
    )
    summary = SelectedActionExecution(
        status=status,
        steps=tuple(_selected_references(draft.scope, step) for step in steps),
        # Keep both final phrase failures in bounded next-turn feedback. The
        # existing host audit below retains earlier correction failures too.
        gate_errors=errors[-MAX_EXECUTION_ERRORS:],
        source_selection=source_selection,
        failure_stage=failure_stage,
    )
    draft.selected_execution = summary
    handles = [
        summarize(request)
        | operation.model_dump(include={"attempt_id", "tool_call_id", "operation_id"})
        for request, operation in zip(draft.requests, draft.operations, strict=True)
    ]
    return [
        {
            "purpose": "Execute selected physical steps",
            "purpose_truncated": False,
            "protocol": protocol,
            "phase": "npc_execution",
            "requests": handles,
            "results": [
                result_summary(operation.model_dump(exclude_none=True) | {"status": "staged"})
                for operation in draft.operations
            ],
            "status": summary.status,
            "stop": summary.status,
            "repaired": repaired,
            "gate_errors": [failure.model_dump() for failure in errors],
            **(
                {"source_selection": source_selection.model_dump(mode="json", exclude_none=True)}
                if source_selection is not None
                else {}
            ),
            **({"error_type": summary.gate_errors[-1].code} if status == "rejected" else {}),
            **({"failure_stage": failure_stage} if failure_stage is not None else {}),
        }
    ]


async def _calls(
    manager: Any,
    settings: Settings,
    usage: Usage,
    llm: Any,
    messages: list[dict],
    offered: list[dict],
    seen_ids: set[str],
) -> tuple[ToolCall, ...]:
    try:
        response = await inference.tool_request(
            manager,
            settings,
            usage,
            messages,
            offered,
            llm=llm,
            phase="npc_execution",
            require_tools=True,
            output_limit=settings.max_output_tokens,
        )
    except inference.ToolEnvelopeError as exc:
        seen_ids.update(exc.call_ids)
        code = {
            "required_tool_missing": "declared_action_without_operation",
            "unavailable_function": "goal_operation_mismatch",
        }.get(exc.code, exc.code)
        raise ExecutionGateError(code) from exc
    return tuple(response.calls)


async def execute(
    manager: Any,
    settings: Settings,
    usage: Usage,
    tools: Tools,
    llm: Any,
    captured: Mapping,
    seen_ids: set[str],
    steps: Sequence[Request],
) -> list[dict]:
    draft = _bound(manager, tools, captured, tools.current_actions())
    protocol = "json" if getattr(llm, "protocol", "native") == "json" else "native"
    if not steps:
        draft.approved = True
        return _audit(draft, protocol, "not_attempted", [], False, steps)
    if len(steps) > MAX_SELECTED_STEPS or any(
        ACTION_MODELS.get(step.tool) is not type(step) or step.tool == "discard_actions"
        for step in steps
    ):
        raise ValueError("Physical execution requires at most two typed world operations.")
    # Snapshot the accepted operands before waiting on an external provider.
    steps = tuple(step.model_copy(deep=True) for step in steps)
    offered = definitions({step.tool for step in steps})
    operand_list = [step.model_dump(mode="json", exclude_none=True) for step in steps]
    messages = [
        {"role": "system", "content": INSTRUCTION},
        {
            "role": "user",
            "content": json.dumps(
                {"steps": operand_list}, ensure_ascii=False, separators=(",", ":")
            ),
        },
    ]
    failures: list[ExecutionGateError] = []
    repaired = False
    while True:
        try:
            calls = await _calls(manager, settings, usage, llm, messages, offered, seen_ids)
            _bound(manager, tools, captured, draft)
            _match(calls, seen_ids, steps)
            issued = [
                turn_controls.operation(
                    captured, call.name, actor_id=draft.scope.actor_id, tool_call_id=call.id
                )
                for call in calls
            ]
            draft.append_selected(steps, issued=issued)
        except SelectedStepRejectedError as exc:
            # Repeating the same call cannot change actual custody or any owner precondition.
            failures.append(ExecutionGateError(exc.reason_code, f"/steps/{exc.index}"))
            break
        except ExecutionGateError as exc:
            _bound(manager, tools, captured, draft)
            failures.append(exc)
            if not _repair_available(manager, settings, usage):
                break
            messages.append(
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "correction": exc.feedback(),
                            "instruction": "No step was staged. Retry all selected steps in order. Copy their arguments exactly.",
                        }
                    ),
                }
            )
            if (
                inference.tool_input_size(llm, messages, offered, require_tools=True)
                > settings.max_input_chars
            ):
                break
            usage.proposal_repairs += 1
            repaired = True
            continue
        draft.approved = True
        return _audit(draft, protocol, "staged", failures, repaired, steps)
    # The accepted social choice survives. Its unexecuted physical intent authorizes no effects.
    draft.approved = True
    return _audit(draft, protocol, "rejected", failures, repaired, steps)
