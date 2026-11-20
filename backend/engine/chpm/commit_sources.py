"""Recheck dependencies and advance optional source queues inside the turn transaction."""

from typing import Any

from backend.engine.chpm import recovery_queue, reports
from backend.engine.npc_actions import acknowledgment


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
    from backend.engine.chpm.notebook_store import persist_workspace

    for actor, draft in getattr(turn, "notebook_drafts", {}).items():
        if (
            actor in turn.decisions
            and actor in turn.minds
            and draft.committable
            and draft.workspace.changed
        ):
            await persist_workspace(
                manager.db, turn.minds[actor], draft.workspace, owner_id=manager.user.id
            )
    # Extraction and pending writes can await after narration review. Recheck the
    # consumed feedback last, inside this transaction, before synchronous delivery.
    await acknowledgment.validate_current(manager, turn)
