"""Shared source and route validation for narration and bounded VN recovery."""

from typing import Any

from backend.core.text_evidence import require_span
from backend.engine.narrated_movement.outcomes import MovementBlockedError
from backend.engine.narrated_movement.schema import MovementProposal


def validate(proposal: MovementProposal, pending: Any) -> None:
    require_span(pending.narration, proposal.evidence, proposal.evidence_span)
    if proposal.evidence not in pending.narration or proposal.basis != "completed":
        raise ValueError("Movement requires exact evidence of a completed current action.")
    actor = pending.before["actors"].get(proposal.actor_id)
    if actor is None or proposal.actor_id in pending.denied:
        raise ValueError("Actor is unavailable or the action was rejected.")
    if not actor["can_move"]:
        raise MovementBlockedError("This actor cannot move.")
    destination = proposal.destination_scene_id
    if (
        destination
        and destination != pending.before["scene_id"]
        and destination not in actor["allowed_destinations"]
    ):
        raise MovementBlockedError("Destination is not an open permitted adjacent location.")
    if proposal.actor_id == "__player__" and (
        not proposal.player_evidence or proposal.player_evidence not in pending.player_message
    ):
        raise ValueError("Player travel lacks exact authorization in the current player message.")
