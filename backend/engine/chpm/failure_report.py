"""Owner-only proposal diagnostics; reading a replay never restores its world or psyche."""

from typing import Any

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.engine.chpm.continuation import StatusProjection
from backend.engine.chpm.schema import KernelState
from backend.engine.chpm.state import KEY
from backend.models.session_state import SessionState
from backend.models.turn_replay import TurnReplay


def _report(current: KernelState | StatusProjection) -> dict[str, Any] | None:
    if not current.recovery.pending_gap_turns:
        return None
    if (
        current.usage.simplified
        and current.usage.fallback_reason == "analysis_failed"
        and current.usage.proposal_feedback
    ):
        return {
            "reason": "analysis_failed",
            "proposal_feedback": current.usage.proposal_feedback,
            "reply_id": current.recovery.recent[-1].reply_id if current.recovery.recent else None,
            "source": "current_turn",
        }
    for record in reversed(current.recovery.recent):
        if (
            record.reason == "analysis_failed"
            and record.proposal_feedback
            and set(record.actor_ids).issubset(current.settings.actor_ids)
        ):
            return {
                "reason": record.reason,
                "proposal_feedback": record.proposal_feedback,
                "reply_id": record.reply_id,
                "source": "recent_turn",
            }
    return None


def _snapshot(value: Any, session_id: str) -> StatusProjection | None:
    if not isinstance(value, dict) or value.get("version") != 1:
        return None
    before = value.get("state")
    if not isinstance(before, dict) or before.get("session_id") != session_id:
        return None
    states = before.get("entity_states")
    if not isinstance(states, dict) or not isinstance(states.get(KEY), dict):
        return None
    try:
        return StatusProjection.model_validate(states[KEY])
    except ValidationError:
        return None


async def latest(
    db: AsyncSession, state: SessionState, current: KernelState
) -> dict[str, Any] | None:
    report = _report(current)
    if report is not None or not current.recovery.pending_gap_turns:
        return report
    replay = await db.get(TurnReplay, state.session_id)
    if replay is None or replay.status != "ready":
        return None
    prior = _snapshot(replay.before, state.session_id)
    if prior is None or (prior.settings.mode, prior.settings.actor_ids) != (
        current.settings.mode,
        current.settings.actor_ids,
    ):
        return None
    report = _report(prior)
    return {**report, "source": "previous_turn_snapshot"} if report is not None else None
