"""Defer one rejected intention through the existing inactive-character boundary."""

import logging
from typing import Any

from backend.engine.chpm.errors import ProposalRejectedError

logger = logging.getLogger(__name__)


def can_defer(turn: Any, error: BaseException) -> bool:
    settings = turn.initial.settings
    return (
        settings.mode == "live"
        and settings.failure_policy == "continue"
        and isinstance(error, ProposalRejectedError)
    )


def defer(turn: Any, actor: str, error: ProposalRejectedError) -> None:
    turn.usage.actor_failures[actor] = str(error)[:600]
    turn.deferred_names[actor] = turn.names.pop(actor, actor)
    # Preparation adds current observations before a proposal is attempted. None
    # of that actor's turn-local draft may leak into a peer's successful commit.
    for field in (
        "decisions",
        "minds",
        "memories",
        "agendas",
        "causal_threads",
        "reconciled_minds",
        "semantic_hits",
    ):
        getattr(turn, field).pop(actor, None)
    turn.gap_cursors.pop(actor, None)
    if actor in turn.initial.recovery.gap_cursors:
        turn.gap_cursors[actor] = turn.initial.recovery.gap_cursors[actor]
    turn.usage.detail = (
        f"NPC proposals paused for {len(turn.usage.actor_failures)} character(s). "
        "Their last confirmed state is preserved. Other decisions are saved only "
        "after the shared narration check."
    )
    logger.warning("NPC proposal deferred: actor=%s error=%s", actor, type(error).__name__)


def require_survivor(turn: Any, failures: list[ProposalRejectedError]) -> None:
    if failures and not turn.decisions:
        # Without an independent accepted proposal, keep the established whole-
        # turn recovery policy. Strict mode never takes the per-actor path.
        raise failures[0]
