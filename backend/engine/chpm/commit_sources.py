"""Recheck dependencies and advance optional source queues inside the turn transaction."""

from typing import Any

from backend.engine.chpm import recovery_queue, reports


async def prepare(manager: Any, turn: Any) -> None:
    if (
        turn is None
        or turn.simplified
        or turn.initial.settings.mode != "live"
        or turn.verdict is None
        or not turn.verdict.matches
    ):
        return
    await reports.validate_commit(manager, turn)
    await recovery_queue.commit(manager, turn)
