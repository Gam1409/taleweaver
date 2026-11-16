"""Reuse the item extraction call and commit facts with their actual assistant source."""

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

from backend.core.engine_detailed_trace import sync_step
from backend.core.state_rejection_trace import reject
from backend.engine.physical_conditions.ledger import apply, read
from backend.engine.physical_conditions.references import bind_records
from backend.engine.physical_conditions.schema import KEY


async def player_report(manager: Any, message_id: str) -> tuple[str, str] | None:
    from backend.models.chat import ChatMessage

    message = await manager.db.get(ChatMessage, message_id)
    if (
        message
        and message.role == "user"
        and not message.is_debug
        and message.session_id == manager.state.session_id
    ):
        return message.id, message.content
    return None


@dataclass
class Pending:
    proposals: list[Any]
    targets: set[str]
    before: Any
    error: str = ""
    item_targets: set[str] = field(default_factory=set)
    player_message: tuple[str, str] | None = None

    def complete(
        self, proposals: list[Any], targets: set[str], *, item_targets: set[str] | None = None
    ) -> None:
        self.proposals = deepcopy(proposals)
        self.targets = set(targets)
        self.error = ""
        self.item_targets = set(item_targets or ())


def discard(manager: Any) -> None:
    manager._pending_physical_conditions = None


def stage(manager: Any, proposals: list[Any], targets: set[str], *, error: str = "") -> Pending:
    pending = Pending(
        deepcopy(proposals),
        set(targets),
        deepcopy((manager.state.entity_states or {}).get(KEY)),
        error,
    )
    manager._pending_physical_conditions = pending
    return pending


@sync_step("physical_conditions.commit")
def finish(manager: Any, message: Any) -> list[str]:
    pending = getattr(manager, "_pending_physical_conditions", None)
    discard(manager)
    if not isinstance(pending, Pending):
        return []
    states = manager.state.entity_states or {}
    if states.get(KEY) != pending.before:
        reject(
            "physical_conditions",
            "stale_state",
            "Saved state changed during the check.",
            proposals=pending.proposals,
            expected_state=pending.before,
            current_state=states.get(KEY),
            message_id=getattr(message, "id", None),
        )
        return ["Physical condition changes need review: the saved state changed during the check."]
    try:
        if pending.error:
            reject(
                "physical_conditions",
                "unconfirmed_check",
                pending.error,
                proposals=pending.proposals,
                message_id=getattr(message, "id", None),
            )
            ledger = read(states)
            ledger.last_check = {
                "message_id": message.id,
                "status": "failed",
                "reason": pending.error,
            }
            manager.state.entity_states = {**states, KEY: ledger.model_dump()}
            return []  # The shared extraction already displayed its failure.
        ledger = read(states)
        if ledger.last_check.get("message_id") == message.id:
            return []
        proposals, bindings = bind_records(ledger, pending.proposals)
        result, _, errors = apply(
            states,
            proposals,
            targets=pending.targets,
            narration=message.content,
            message_id=message.id,
            session_id=manager.state.session_id,
            minute=int(manager.state.in_game_time or 0),
            item_targets=pending.item_targets,
            player_message=pending.player_message,
        )
        if bindings:
            result[KEY]["last_check"]["reference_bindings"] = bindings
    except ValueError as error:
        reject(
            "physical_conditions",
            "invalid_state",
            "The physical ledger could not be validated.",
            validation_reason=str(error),
            proposals=pending.proposals,
            message_id=getattr(message, "id", None),
        )
        return [
            "Physical condition state is invalid and was preserved. Review it in Debug → State."
        ]
    manager.state.entity_states = result
    if errors:
        reject(
            "physical_conditions",
            "proposals_rejected",
            "Some physical or item-state proposals were rejected.",
            proposals=pending.proposals,
            errors=errors,
            message_id=getattr(message, "id", None),
            audit=result.get(KEY, {}).get("last_check"),
            narration=message.content,
        )
    return (
        [
            "Some physical condition changes were not applied. Existing facts were preserved; review Debug → State."
        ]
        if errors
        else []
    )
