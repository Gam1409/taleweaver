"""Reuse the item extraction call and commit facts with their actual assistant source."""

from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from backend.engine.physical_conditions.ledger import apply, read
from backend.engine.physical_conditions.schema import KEY


@dataclass
class Pending:
    proposals: list[Any]
    targets: set[str]
    before: Any
    error: str = ""

    def complete(self, proposals: list[Any], targets: set[str]) -> None:
        self.proposals = deepcopy(proposals)
        self.targets = set(targets)
        self.error = ""


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


def finish(manager: Any, message: Any) -> list[str]:
    pending = getattr(manager, "_pending_physical_conditions", None)
    discard(manager)
    if not isinstance(pending, Pending):
        return []
    states = manager.state.entity_states or {}
    if states.get(KEY) != pending.before:
        return ["Physical condition changes need review: the saved state changed during the check."]
    try:
        if pending.error:
            ledger = read(states)
            ledger.last_check = {
                "message_id": message.id,
                "status": "failed",
                "reason": pending.error,
            }
            manager.state.entity_states = {**states, KEY: ledger.model_dump()}
            return []  # The shared extraction already displayed its failure.
        result, _, errors = apply(
            states,
            pending.proposals,
            targets=pending.targets,
            narration=message.content,
            message_id=message.id,
            session_id=manager.state.session_id,
            minute=int(manager.state.in_game_time or 0),
        )
    except ValueError:
        return [
            "Physical condition state is invalid and was preserved. Review it in Debug → State."
        ]
    manager.state.entity_states = result
    return (
        [
            "Some physical condition changes were not applied. Existing facts were preserved; review Debug → State."
        ]
        if errors
        else []
    )
