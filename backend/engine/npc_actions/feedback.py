"""Project current rejected command previews from the existing decision audit."""

import re
from hashlib import sha256
from typing import Any

from backend.engine import turn_controls
from backend.engine.chpm.agent_limits import MAX_AGENT_ROUNDS
from backend.engine.npc_actions import control
from backend.engine.npc_actions.contracts import ACTION_MODELS, Request

FIELDS = frozenset(
    {"item_id", "target_id", "recipient_id", "destination_scene_id", "dimension", "posture", "mode"}
)
_REQUIRED = {
    "move_to": {"destination_scene_id"},
    "set_pose": {"posture"},
    "approach": {"target_id"},
    "interact": {"target_id"},
    "change_item_state": {"item_id", "dimension"},
    "give_item": {"item_id", "recipient_id"},
}
_CUSTODY = {"take_item", "give_item", "put_down_item"}
_WARDROBE = {"wear_item", "take_off_item", "adjust_clothing"}
_REASON_CODES = frozenset(control.MESSAGES) | {
    "unavailable_actions",
    "batch_rejected",
    "invalid_arguments",
    "invalid_json",
    "invalid_tool",
    "invalid_request",
}
_REJECTED_STATUSES = frozenset(
    {
        "blocked",
        "unavailable_entity",
        "unavailable_actions",
        "plan_closed",
        "action_limit",
        "scene_frame_ended",
        "batch_rejected",
        "invalid_arguments",
        "invalid_json",
        "invalid_tool",
        "invalid_request",
    }
)
INSTRUCTIONS = """
Rejected previews did not change the world. rejected_command_previews contains
current typed tool feedback, not physical failed attempts or completed effects.
Do not narrate its rejected take/give/wear/travel/pose as completed. Keep compatible
speech, gestures and independent effects free. Later authoritative applied outcomes
supersede only superseded_fields on the same referenced actor/item; other denials
remain. An earlier rejected operation never becomes successful retroactively.
discarded_plan marks abandoned planning, not an obstacle or a permanent prohibition.
"""


def summarize(request: Request) -> dict:
    """Retain bounded semantic references, never free descriptions or private arguments."""
    return request.model_dump(mode="json", include={"tool", *FIELDS}, exclude_none=True)


def project(turn: Any) -> dict[str, list[dict]]:
    """Resolve only this attempt's complete, host-correlated action audit records."""
    effects = _applied_fields(turn)
    output = {}
    seen: set[str] = set()
    for actor, decision in getattr(turn, "decisions", {}).items():
        rows = _actor_records(turn, actor, decision)
        identifiers = {row["operation_id"] for row in rows}
        if seen & identifiers:
            raise control.CommandRejectedError("invalid_operation")
        seen.update(identifiers)
        discarded = max(
            (index for index, row in enumerate(rows) if row["status"] == "discarded"),
            default=-1,
        )
        rejected = [
            _rejection(row, actor, effects, index < discarded)
            for index, row in enumerate(rows)
            if row["status"] in _REJECTED_STATUSES
        ]
        if rejected:
            output[actor] = rejected
    return output


def instructions(turn: Any) -> str:
    return INSTRUCTIONS if project(turn) else ""


def _actor_records(turn: Any, actor: str, decision: Any) -> list[dict]:
    if _retained_audit(turn, actor, decision):
        return []
    audit = decision.agent_audit
    if len(audit) > MAX_AGENT_ROUNDS:
        raise control.CommandRejectedError("invalid_operation")
    rows = [row for step in audit for row in _round_records(turn, actor, decision, step)]
    if len({row["operation_id"] for row in rows}) != len(rows):
        raise control.CommandRejectedError("invalid_operation")
    return rows


def _retained_audit(turn: Any, actor: str, decision: Any) -> bool:
    previous = getattr(getattr(turn, "initial", None), "actors", {}).get(actor)
    return bool(
        previous is not None
        and previous.actor_id == decision.actor_id == actor
        and previous.observation == decision.observation
        and previous.context_hash == decision.context_hash
        and getattr(previous, "selected", None) == getattr(decision, "selected", None)
        # Exact audit equality includes the retained operation and call IDs.
        and previous.agent_audit == decision.agent_audit
    )


def _round_records(turn: Any, actor: str, decision: Any, step: dict) -> list[dict]:
    requests = step.get("requests", [])
    results = step.get("results", [])
    if (
        not isinstance(requests, list)
        or not isinstance(results, list)
        or len(requests) > 2
        or len(results) > 2
        or any(not isinstance(row, dict) for row in [*requests, *results])
    ):
        raise control.CommandRejectedError("invalid_operation")
    by_call = _by_call(results)
    rows = [_record(turn, actor, decision, request, by_call) for request in requests]
    return [row for row in rows if row is not None]


def _record(turn: Any, actor: str, decision: Any, request: dict, by_call: dict) -> dict | None:
    tool = request.get("tool")
    if not isinstance(tool, str):
        raise control.CommandRejectedError("invalid_operation")
    # Old audit summaries have no control authority; keep them readable.
    if tool not in ACTION_MODELS or "operation_id" not in request or _legacy_summary(request):
        return None
    call_id = request.get("tool_call_id")
    result = by_call.get(call_id) if isinstance(call_id, str) else None
    if not isinstance(result, dict):
        raise control.CommandRejectedError("invalid_operation")
    operation = _operation(turn, actor, decision, request, result)
    return {
        **_references(request, result["status"]),
        "operation_id": operation.operation_id,
        "tool_call_id": operation.tool_call_id,
        "phase": operation.phase,
        "status": result["status"],
        "reason_code": result.get("reason_code", "owner_rejected"),
    }


def _legacy_summary(request: dict) -> bool:
    return request.get("path_hash") == sha256(b"").hexdigest() and request.keys() <= {
        "tool",
        "path_hash",
        "attempt_id",
        "operation_id",
        "tool_call_id",
    }


def _by_call(results: list[dict]) -> dict:
    bound = [result for result in results if result.get("tool_call_id") is not None]
    keys = [result["tool_call_id"] for result in bound]
    if any(not isinstance(key, str) for key in keys) or len(keys) != len(set(keys)):
        raise control.CommandRejectedError("invalid_operation")
    return {result["tool_call_id"]: result for result in bound}


def _operation(
    turn: Any, actor: str, decision: Any, request: dict, result: dict
) -> turn_controls.Operation:
    if not isinstance(result, dict):
        raise control.CommandRejectedError("invalid_operation")
    try:
        operation = turn_controls.Operation.model_validate(
            {key: result[key] for key in turn_controls.Operation.model_fields if key in result}
        )
    except ValueError:
        raise control.CommandRejectedError("invalid_operation") from None
    observation = decision.observation
    if (
        not control.bound_to(operation, turn.control)
        or operation.phase != "npc_tools"
        or operation.actor_id != actor
        or decision.actor_id != actor
        or operation.tool != request["tool"]
        or not operation.tool_call_id
        or operation.tool_call_id != request.get("tool_call_id")
        or operation.operation_id != request.get("operation_id")
        or operation.attempt_id != request.get("attempt_id")
        or operation.input_id != turn.input_id
        or operation.input_id != observation.message_id
        or operation.input_revision != observation.revision_id
        or operation.input_hash != observation.content_hash
        or not isinstance(result.get("status"), str)
        or result["status"] not in (_REJECTED_STATUSES | {"staged", "discarded"})
    ):
        raise control.CommandRejectedError("invalid_operation")
    return operation


def _references(request: dict, status: str) -> dict:
    if "arguments_hash" in request:
        if status not in {"invalid_arguments", "invalid_json", "batch_rejected"} or any(
            not isinstance(request.get(key), str)
            or re.fullmatch(r"[a-f0-9]{64}", request[key]) is None
            for key in ("arguments_hash", "name_hash")
        ):
            raise control.CommandRejectedError("invalid_operation")
        return {"tool": request["tool"]}
    values = {key: value for key, value in request.items() if key in {"tool", *FIELDS}}
    tool = values["tool"]
    required = _REQUIRED.get(tool, {"item_id"} if tool not in {"discard_actions"} else set())
    if not required <= values.keys() or any(
        not isinstance(value, str) or not 0 < len(value) <= 100 for value in values.values()
    ):
        raise control.CommandRejectedError("invalid_operation")
    if "posture" in values:
        from backend.engine.npc_actions.contracts import Pose

        try:
            Pose(tool="set_pose", posture=values["posture"])
        except ValueError:
            raise control.CommandRejectedError("invalid_operation") from None
    if "mode" in values and values["mode"] not in {"walk", "crawl", "run"}:
        raise control.CommandRejectedError("invalid_operation")
    return values


def _rejection(row: dict, actor: str, effects: set[tuple], discarded: bool) -> dict:
    fields = _owned_fields(row, actor)
    result = {
        **row,
        "reason_code": row["reason_code"]
        if isinstance(row["reason_code"], str) and row["reason_code"] in _REASON_CODES
        else "owner_rejected",
    }
    superseded = sorted(field[0] for field in fields if field in effects)
    if superseded:
        result["superseded_fields"] = superseded
    if discarded:
        result["discarded_plan"] = True
    return result


def _owned_fields(request: dict, actor: str) -> set[tuple]:
    tool = request["tool"]
    if not {"item_id", "target_id", "posture", "destination_scene_id"} & request.keys():
        return set()
    if tool in _CUSTODY:
        return {("custody", request["item_id"])}
    if tool in _WARDROBE:
        return {("wardrobe", actor, request["item_id"])}
    if tool in {"change_item_state", "use_item"}:
        return {("item_state", request["item_id"], request.get("dimension", "usage").casefold())}
    return {
        "move_to": {("scene", actor)},
        "set_pose": {("posture", actor)},
        "approach": {("posture", actor), ("placement", actor)},
    }.get(tool, set())


def _applied_fields(turn: Any) -> set[tuple]:
    return {
        field
        for actor, outcomes in control.validated_outcomes(turn).items()
        for result in outcomes
        if result.get("status") == "applied"
        for field in _effect_fields(result.get("effect", {}), actor)
    }


def _effect_fields(effect: dict, actor: str) -> set[tuple]:
    fields: set[tuple] = set()
    item = effect.get("item_id")
    if item and "destination_owner" in effect:
        fields.add(("custody", item))
    if item and effect.get("operation") in {"wear", "remove", "adjust"}:
        fields.add(("wardrobe", actor, item))
    if item and isinstance(effect.get("dimension"), str):
        fields.add(("item_state", item, effect["dimension"].casefold()))
    if "destination_scene_id" in effect:
        fields.add(("scene", actor))
    if "posture" in effect:
        fields.add(("posture", actor))
    if "placement" in effect:
        fields.add(("placement", actor))
    return fields
