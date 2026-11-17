"""Typed command outcomes with stable operation identity and host-rendered refusals."""

from collections.abc import Mapping
from typing import Any
from uuid import uuid4

from backend.core.diagnostic_failures import failure_reason
from backend.core.state_rejection_trace import reject
from backend.engine import turn_controls
from backend.engine.narrated_items.errors import (
    POLICY_MESSAGES,
    TRANSFER_MESSAGES,
    ItemPolicyError,
    ItemTransferError,
)

MESSAGES: dict[str, str] = {
    "plan_closed": "This decision has already been submitted.",
    "action_limit": "Submit or discard the existing plan.",
    "scene_frame_ended": "Room travel ends this scene's plan. Submit it or discard it first.",
    "unavailable_entity": "Choose an exact currently accessible entity ID; find or inspect it first.",
    "owner_rejected": "The command could not be validated against current owner state.",
    "stale": "The controlling attempt, input or settings changed before publication.",
    "skipped_dependency": "An earlier command did not complete; this dependent command did not run.",
    "invalid_operation": "The operation record does not belong to this command or attempt.",
    "preliminary_item_rejected": "The preliminary item proposal could not be validated against canonical possessions.",
    "preliminary_item_deferred": "The item proposal is pending the responsible actor's decision.",
}
MESSAGES.update(POLICY_MESSAGES.items())
MESSAGES.update(TRANSFER_MESSAGES.items())


class CommandRejectedError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code if code in MESSAGES else "owner_rejected"
        super().__init__(MESSAGES[self.code])


def reason(error: ValueError | TypeError) -> str:
    """Legacy owner errors retain a generic code; prose never determines classification."""
    return (
        error.code
        if isinstance(error, (CommandRejectedError, ItemTransferError, ItemPolicyError))
        else "owner_rejected"
    )


def result(operation: turn_controls.Operation, status: str, **fields: Any) -> dict:
    code = fields.pop("reason_code", None)
    return {
        **operation.model_dump(exclude_none=True),
        "event_id": "event_" + uuid4().hex,
        "status": status,
        **fields,
        **(
            {"reason_code": code, "message": MESSAGES.get(code, MESSAGES["owner_rejected"])}
            if code
            else {}
        ),
    }


def trace_failure(
    operation: turn_controls.Operation, error: ValueError | TypeError, code: str
) -> dict:
    detail = failure_reason(error, "Owner validation failed.")
    reject(
        "npc_actions",
        "npc_actions." + code,
        MESSAGES.get(code, MESSAGES["owner_rejected"]),
        diagnostic_detail=detail,
        diagnostic_error_type=type(error).__name__,
        operation=operation.model_dump(exclude_none=True),
    )
    return {"diagnostic_detail": detail[:4096], "diagnostic_error_type": type(error).__name__}


def owner_failure(operation: turn_controls.Operation, error: ValueError, **fields: Any) -> dict:
    code = reason(error)
    return result(
        operation, "blocked", reason_code=code, **trace_failure(operation, error, code), **fields
    )


def same_operation(raw: Mapping, expected: turn_controls.Operation) -> bool:
    """Correlate by host operation identity, never by the result's list position."""
    try:
        actual = turn_controls.Operation.model_validate(
            {key: raw[key] for key in turn_controls.Operation.model_fields if key in raw}
        )
    except (ValueError, TypeError, KeyError):
        return False
    fields = (
        "attempt_id",
        "phase",
        "input_id",
        "input_revision",
        "input_hash",
        "operation_id",
        "tool",
        "actor_id",
        "command_id",
        "tool_call_id",
    )
    return all(getattr(actual, key) == getattr(expected, key) for key in fields)


def bound_to(operation: turn_controls.Operation, captured: Mapping) -> bool:
    expected = turn_controls.binding(captured)
    fields = ("attempt_id", "input_id", "input_revision", "input_hash")
    return all(getattr(operation, key) == getattr(expected, key) for key in fields)


def local_scope(scope: Any) -> dict:
    """Bound direct owner tests locally; production capture uses the stream's attempt."""
    return turn_controls.Binding(
        attempt_id=uuid4().hex,
        phase="npc_command_preview",
        input_id=scope.input_id,
        input_revision=scope.input_revision,
        input_hash=scope.input_hash or turn_controls.fingerprint(None),
        state_revision=turn_controls.fingerprint(scope.states),
    ).model_dump()


def validated_outcomes(turn: Any) -> dict[str, list[dict]]:
    """Review and state consumers admit only this captured attempt's complete records."""
    outcomes = getattr(turn, "action_outcomes", {})
    drafts = getattr(turn, "action_drafts", {})
    if not any(outcomes.values()) and not any(
        getattr(drafts.get(actor), "operations", ()) for actor in outcomes
    ):
        return outcomes
    captured = getattr(turn, "control", None)
    if not captured:
        raise CommandRejectedError("invalid_operation")
    identifiers = set()
    for actor, rows in outcomes.items():
        draft = drafts.get(actor)
        issued = {
            operation.operation_id: operation for operation in getattr(draft, "operations", ())
        }
        supplied = set()
        for row in rows:
            operation = _publication_record(row, actor, captured)
            expected = issued.get(operation.operation_id)
            if (
                operation.operation_id in identifiers
                or expected is None
                or not same_operation(
                    row, expected.model_copy(update={"phase": "npc_command_publication"})
                )
            ):
                raise CommandRejectedError("invalid_operation")
            identifiers.add(operation.operation_id)
            supplied.add(operation.operation_id)
        if supplied != issued.keys():
            raise CommandRejectedError("invalid_operation")
    return outcomes


def model_outcomes(turn: Any) -> dict[str, list[dict]]:
    return {
        actor: [
            {key: value for key, value in row.items() if not key.startswith("diagnostic_")}
            for row in rows
        ]
        for actor, rows in validated_outcomes(turn).items()
    }


def _publication_record(raw: Any, actor: str, captured: Mapping) -> turn_controls.Operation:
    if not isinstance(raw, dict):
        raise CommandRejectedError("invalid_operation")
    try:
        operation = turn_controls.Operation.model_validate(
            {key: raw[key] for key in turn_controls.Operation.model_fields if key in raw}
        )
    except (ValueError, TypeError):
        raise CommandRejectedError("invalid_operation") from None
    if (
        not bound_to(operation, captured)
        or operation.phase != "npc_command_publication"
        or operation.actor_id != actor
        or not isinstance(raw.get("status"), str)
        or (raw.get("status") == "applied" and not isinstance(raw.get("effect"), dict))
    ):
        raise CommandRejectedError("invalid_operation")
    return operation
