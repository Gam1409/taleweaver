"""Commit validated narration movements through the existing world event applier."""

from collections import Counter
from copy import deepcopy
from dataclasses import dataclass
from hashlib import sha256
from typing import Any

from pydantic import ValidationError
from sqlalchemy import select

from backend.core.engine_detailed_trace import step
from backend.core.text_evidence import require_span
from backend.engine.clothing.visuals import session_objects
from backend.engine.gameplay.turn_state_applier import TurnStateApplier
from backend.engine.narrated_movement.context import context
from backend.engine.narrated_movement.schema import MovementProposal
from backend.engine.rule_engine import EntityMovement, GameEvent, WorldEntityUpdate
from backend.engine.scene_continuity.runtime import follow_transition
from backend.models.chat import ChatMessage

MAX_MOVEMENTS = 8


@dataclass
class Pending:
    before: dict
    narration: str
    player_message: str
    proposals: list[Any] | None = None
    denied: frozenset[str] = frozenset()


async def prepare(manager: Any, rows: list[Any], narration: str) -> dict:
    before = await context(manager, rows)
    player_id = getattr(manager, "_vn_player_message_id", None)
    player_message = (
        await manager.db.scalar(
            select(ChatMessage.content).where(
                ChatMessage.id == player_id,
                ChatMessage.session_id == manager.state.session_id,
                ChatMessage.role == "user",
            )
        )
        if player_id
        else None
    )
    manager._pending_narrated_movement = Pending(before, narration, player_message or "")
    return {**before, "current_player_message": player_message or ""}


def complete(
    manager: Any, proposals: list[Any], *, denied: set[str] | None = None, confirmed: bool = True
) -> None:
    pending = getattr(manager, "_pending_narrated_movement", None)
    if isinstance(pending, Pending) and confirmed:
        pending.proposals = deepcopy(proposals)
        pending.denied = frozenset(denied or ())


@step("movement.narration.commit")
async def finish(manager: Any, message: Any) -> list[str]:
    pending = getattr(manager, "_pending_narrated_movement", None)
    manager._pending_narrated_movement = None
    if not isinstance(pending, Pending) or pending.proposals is None:
        return []
    if not pending.proposals:
        return await _review(manager, message, [], [])
    rows = await session_objects(manager.db, manager.state.session_id)
    if pending.narration != message.content or pending.before != await context(manager, rows):
        return await _review(
            manager, message, [], ["The movement source state changed during extraction."]
        )
    event, accepted, errors = _event(pending)
    applied = await TurnStateApplier(manager).apply_narrated_movement(event) if accepted else []
    if manager.state.current_scene_id != pending.before["scene_id"]:
        message.scene_id = manager.state.current_scene_id
        await follow_transition(manager)
    return [*applied, *await _review(manager, message, accepted, errors)]


def _event(pending: Pending) -> tuple[GameEvent, list[dict], list[str]]:
    event, accepted, errors = GameEvent(), [], []
    entries = pending.proposals or []
    if len(entries) > MAX_MOVEMENTS:
        return event, [], ["Too many movement proposals; no movement in this batch was applied."]
    counts = Counter(
        row.get("actor_id")
        for row in entries
        if isinstance(row, dict) and isinstance(row.get("actor_id"), str)
    )
    for index, raw in enumerate(entries):
        try:
            proposal = MovementProposal.model_validate(raw)
            if counts[proposal.actor_id] > 1:
                raise ValueError("Multiple final movements for one actor are ambiguous.")
            _validate(proposal, pending)
            _append(event, proposal, pending.before["scene_id"])
            accepted.append(proposal.model_dump())
        except ValidationError:
            errors.append(
                f"Movement proposal {index + 1}: Invalid movement fields or source reference."
            )
        except ValueError as exc:
            errors.append(f"Movement proposal {index + 1}: {exc}")
    return event, accepted, errors


def _validate(proposal: MovementProposal, pending: Pending) -> None:
    require_span(pending.narration, proposal.evidence, proposal.evidence_span)
    if proposal.evidence not in pending.narration or proposal.basis != "completed":
        raise ValueError("Movement requires exact evidence of a completed current action.")
    actor = pending.before["actors"].get(proposal.actor_id)
    if actor is None or proposal.actor_id in pending.denied:
        raise ValueError("Actor is unavailable or the action was rejected.")
    if not actor["can_move"]:
        raise ValueError("This actor cannot move.")
    destination = proposal.destination_scene_id
    if (
        destination
        and destination != pending.before["scene_id"]
        and destination not in actor["allowed_destinations"]
    ):
        raise ValueError("Destination is not an open permitted adjacent location.")
    if proposal.actor_id == "__player__" and (
        not proposal.player_evidence or proposal.player_evidence not in pending.player_message
    ):
        raise ValueError("Player travel lacks exact authorization in the current player message.")


def _append(event: GameEvent, proposal: MovementProposal, scene_id: str) -> None:
    if proposal.actor_id == "__player__":
        event.new_scene_id = proposal.destination_scene_id
    elif proposal.destination_scene_id and proposal.destination_scene_id != scene_id:
        event.moved_entities = [
            *(event.moved_entities or []),
            EntityMovement(entity_id=proposal.actor_id, to_scene_id=proposal.destination_scene_id),
        ]
    else:
        event.updated_entities = [
            *(event.updated_entities or []),
            WorldEntityUpdate(entity_id=proposal.actor_id, presence=proposal.presence),
        ]


async def _review(manager: Any, message: Any, accepted: list[dict], errors: list[str]) -> list[str]:
    from backend.engine.narrated_items.runtime import KEY

    states = manager.state.entity_states or {}
    check = states.get(KEY)
    if isinstance(check, dict):
        audit = {
            "message_id": message.id,
            "content_hash": sha256(message.content.encode()).hexdigest(),
            "accepted": accepted,
            "rejected": errors,
        }
        manager.state.entity_states = {
            **states,
            KEY: {
                **check,
                "movement_check": audit,
                "status": "needs_review" if errors else check.get("status", "complete"),
                "rejected": [*check.get("rejected", []), *errors],
            },
        }
    if not errors:
        return []
    notice = "Some narrated movements need review; unconfirmed locations were preserved. Review Debug → State."
    await manager._save_chat_message("system", notice)
    return [notice]
