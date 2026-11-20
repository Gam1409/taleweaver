"""One bounded request interprets accepted own prose before the existing atomic draft."""

import json
from collections.abc import Mapping, Sequence
from typing import Any, Literal

from backend.core.llm_tool_turn import ToolCall
from backend.engine import turn_controls
from backend.engine.chpm import (
    agent_native,
    agent_observable,
    inference,
    json_contract,
    physical_resolution,
)
from backend.engine.chpm import (
    two_phase_execution as execution,
)
from backend.engine.chpm.agent_tools import Tools
from backend.engine.chpm.schema import Settings, Usage
from backend.engine.npc_actions import selected_sources, selected_targets
from backend.engine.npc_actions.contracts import Request
from backend.engine.npc_actions.preview import Draft, SelectedStepRejectedError


def _decode(
    calls: tuple[ToolCall, ...], seen_ids: set[str], selection: selected_sources.Selection
) -> tuple[physical_resolution.Resolution, ...]:
    valid = agent_native._valid_envelope(calls, seen_ids)
    seen_ids.update(call.id for call in calls if 0 < len(call.id) <= 128)
    if not valid:
        raise execution.ExecutionGateError("invalid_call_envelope")
    if len(calls) != 1 or calls[0].name != "resolve_selected_steps":
        raise execution.ExecutionGateError("unexpected_operation")
    try:
        body = physical_resolution.Resolutions.model_validate(
            json_contract.decode(calls[0].arguments_raw)
        )
    except ValueError as exc:
        raise execution.ExecutionGateError("invalid_arguments") from exc
    groups = {row.passage_id: row for row in body.resolutions}
    expected = [row.passage_id for row in selection.passages]
    if len(groups) != len(body.resolutions) or set(groups) != set(expected):
        raise execution.ExecutionGateError("source_coverage_mismatch")
    return tuple(groups[key] for key in expected)


def _trace(
    selection: selected_sources.Selection,
    groups: tuple[physical_resolution.Resolution, ...],
    operations: Sequence[turn_controls.Operation],
    call_id: str | None,
) -> selected_sources.SelectionTrace:
    links, index = [], 0
    for group in groups:
        actions = tuple(
            selected_sources.ActionSource(
                ordinal=index + offset,
                operation_id=operations[index + offset].operation_id,
                tool=action.tool,
                depends_on=operations[index + offset - 1].operation_id if index + offset else None,
            )
            for offset, action in enumerate(group.actions)
        )
        index += len(actions)
        links.append(
            selected_sources.ResolutionSource(
                passage_id=group.passage_id,
                disposition=group.disposition,
                reason=group.reason,
                remainder=group.remainder,
                actions=actions,
            )
        )
    return selected_sources.SelectionTrace(
        selection=selection, resolution_call_id=call_id, resolutions=tuple(links)
    )


def _messages(tools: Tools, selection: selected_sources.Selection) -> list[dict]:
    view = agent_observable.current(tools)
    wanted = {key for row in selection.passages for key in row.target_refs}
    entities = (
        [
            {key: row[key] for key in ("id", "name", "kind") if key in row}
            for identifier, row in view.entities.items()
            if identifier in wanted
        ]
        if view is not None
        else []
    )
    payload = {
        "actor_id": selection.control.actor_id,
        "selected_own_phrases": [
            row.model_dump(include={"passage_id", "text", "target_refs"})
            for row in selection.passages
        ],
        "visible_referents": entities,
        "available_destinations": _destinations(tools),
        **agent_observable.index(tools),
    }
    return [
        {"role": "system", "content": physical_resolution.INSTRUCTION},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]


def _destinations(tools: Tools) -> list[dict]:
    draft = tools.current_actions()
    if draft is None:
        return []
    view = agent_observable.current(tools)
    routes = {row["scene_id"]: row for row in view.scene.get("routes", [])} if view else {}
    return [
        {"scene_id": key, "label": str(routes.get(key, {}).get("label", ""))[:80]}
        for key in sorted(draft.scope.destinations)
    ]


def _definition(draft: Draft) -> list[dict]:
    scope = draft.scope
    return physical_resolution.definition(
        draft.available_tools() - {"discard_actions"},
        {
            "item_id": sorted(scope.accessible_ids & scope.possessions.items.keys()),
            "recipient_id": sorted((scope.actors.keys() | {"@player"}) & scope.accessible_ids),
            "target_id": sorted(scope.accessible_ids),
            "destination_scene_id": sorted(scope.destinations),
        },
    )


def _stage(
    draft: Draft,
    selection: selected_sources.Selection,
    groups: tuple[physical_resolution.Resolution, ...],
    issued: Sequence[turn_controls.Operation],
) -> None:
    steps = [action for group in groups for action in group.actions]
    passages = [
        passage
        for passage, group in zip(selection.passages, groups, strict=True)
        for _ in group.actions
    ]

    def validate(trial: Draft, request: Request, index: int) -> None:
        try:
            selected_targets.validate(trial, request, passages[index])
        except selected_targets.TargetResolutionError as exc:
            path = f"/steps/{passages[index].ordinal}/{exc.field}"
            raise execution.ExecutionGateError(exc.code, path) from exc

    draft.append_selected(steps, issued=issued, validate_step=validate)


def _unresolved(
    groups: tuple[physical_resolution.Resolution, ...],
) -> list[execution.ExecutionGateError]:
    return [
        execution.ExecutionGateError(group.reason or "execution_rejected", f"/steps/{index}")
        for index, group in enumerate(groups)
        if group.disposition == "unresolved"
    ]


def _resolution_failures(
    groups: tuple[physical_resolution.Resolution, ...], steps: list[Request], available: set[str]
) -> list[execution.ExecutionGateError]:
    return [
        execution.ExecutionGateError("unavailable_actions", f"/steps/{index}/tool")
        for index, step in enumerate(steps)
        if step.tool not in available
    ] + _unresolved(groups)


def _correct(messages: list[dict], error: execution.ExecutionGateError) -> None:
    messages.append(
        {
            "role": "user",
            "content": json.dumps(
                {
                    "correction": error.feedback(),
                    "instruction": "Nothing was staged. Resolve every original phrase again; do not change the selected conduct or guess ambiguous references.",
                }
            ),
        }
    )


async def execute(
    manager: Any,
    settings: Settings,
    usage: Usage,
    tools: Tools,
    llm: Any,
    captured: Mapping,
    seen_ids: set[str],
    choices: Sequence[selected_sources.Choice],
) -> list[dict]:
    draft = execution._bound(manager, tools, captured, tools.current_actions())
    protocol = "json" if getattr(llm, "protocol", "native") == "json" else "native"
    if not choices:
        draft.approved = True
        return execution._audit(draft, protocol, "not_attempted", [], False, [])
    # Seal accepted own words before any await; late results keep this captured binding.
    selection = selected_sources.capture(dict(captured), draft.scope.actor_id, list(choices))
    unavailable = [
        execution.ExecutionGateError("unavailable_target", f"/steps/{row.ordinal}/target_refs")
        for row in selection.passages
        if set(row.target_refs) - selected_targets.known_references(draft)
    ]
    if unavailable:
        draft.approved = True
        return execution._audit(
            draft,
            protocol,
            "rejected",
            unavailable,
            False,
            [],
            source_selection=selected_sources.SelectionTrace(selection=selection),
            failure_stage="interpretation",
        )
    messages = _messages(tools, selection)
    available = draft.available_tools() - {"discard_actions"}
    offered = _definition(draft)
    failures: list[execution.ExecutionGateError] = []
    failure_stage: Literal["interpretation", "owner_precondition"] = "interpretation"
    repaired = False
    steps: list[Request] = []
    groups: tuple[physical_resolution.Resolution, ...] = ()
    issued: list[turn_controls.Operation] = []
    call_id: str | None = None
    while True:
        steps, groups, issued, call_id = [], (), [], None
        try:
            calls = await execution._calls(
                manager, settings, usage, llm, messages, offered, seen_ids
            )
            execution._bound(manager, tools, captured, draft)
            groups = _decode(calls, seen_ids, selection)
            call_id = calls[0].id
            steps = [action for group in groups for action in group.actions]
            issued = [
                turn_controls.operation(
                    captured, step.tool, actor_id=draft.scope.actor_id, tool_call_id=call_id
                )
                for step in steps
            ]
            rejected = _resolution_failures(groups, steps, available)
            if rejected:
                failures.extend(rejected)
                break
            _stage(draft, selection, groups, issued)
        except SelectedStepRejectedError as exc:
            failure_stage = "owner_precondition"
            failures.append(execution.ExecutionGateError(exc.reason_code, f"/steps/{exc.index}"))
            break
        except execution.ExecutionGateError as exc:
            execution._bound(manager, tools, captured, draft)
            failures.append(exc)
            if exc.code == "ambiguous_target" or not execution._repair_available(
                manager, settings, usage
            ):
                break
            _correct(messages, exc)
            if (
                inference.tool_input_size(llm, messages, offered, require_tools=True)
                > settings.max_input_chars
            ):
                break
            usage.proposal_repairs += 1
            repaired = True
            continue
        draft.approved = True
        return execution._audit(
            draft,
            protocol,
            "staged" if steps else "no_effect",
            failures,
            repaired,
            steps,
            source_selection=_trace(selection, groups, issued, call_id),
        )
    draft.approved = True
    return execution._audit(
        draft,
        protocol,
        "rejected",
        failures,
        repaired,
        steps,
        source_selection=_trace(selection, groups, issued, call_id),
        failure_stage=failure_stage,
    )
