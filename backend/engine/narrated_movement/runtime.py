"""Commit validated narration movements through the existing world event applier."""

from collections import Counter
from copy import deepcopy
from dataclasses import dataclass, field
from hashlib import sha256
from typing import Any

from pydantic import ValidationError
from sqlalchemy import select

from backend.core.engine_detailed_trace import step
from backend.core.state_rejection_trace import reject
from backend.engine import turn_controls
from backend.engine.clothing.visuals import session_objects
from backend.engine.gameplay.turn_state_applier import TurnStateApplier
from backend.engine.narrated_movement.context import context
from backend.engine.narrated_movement.outcomes import MovementBlockedError, MovementOutcome, receipt
from backend.engine.narrated_movement.schema import MAX_MOVEMENTS, MovementProposal
from backend.engine.narrated_movement.validation import validate as _validate
from backend.engine.rule_engine import EntityMovement, GameEvent, WorldEntityUpdate
from backend.engine.scene_continuity.runtime import follow_transition
from backend.models.chat import ChatMessage


@dataclass
class Pending:
    before: dict
    narration: str
    player_message: str
    proposals: list[Any] | None = None
    denied: frozenset[str] = frozenset()
    outcomes: list[MovementOutcome] = field(default_factory=list)
    confirmed: bool = True
    original_count: int = 0
    command_control: dict = field(default_factory=dict)
    command_outcomes: list[MovementOutcome] = field(default_factory=list)


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


def exclude_commands(
    manager: Any, proposals: list[dict], *, original_count: int, control: dict
) -> None:
    """Retain final command denials in the existing owner, never during a correction preview."""
    pending = getattr(manager, "_pending_narrated_movement", None)
    if not isinstance(pending, Pending) or not turn_controls.bind_current(manager, control):
        return
    pending.original_count = original_count
    pending.command_control = deepcopy(control)
    pending.command_outcomes = (
        [
            outcome
            for row in proposals
            if row.get("basis") == "completed"
            and (outcome := receipt(row, pending.narration, "blocked")) is not None
        ]
        if len(proposals) <= original_count <= MAX_MOVEMENTS
        else []
    )


def _command_current(manager: Any, pending: Pending, message: Any, scene_id: str | None) -> bool:
    return (
        message.content == pending.narration
        and message.session_id == manager.game_id
        and message.role == "assistant"
        and (scene_id or pending.before["scene_id"]) == manager.state.current_scene_id
        and turn_controls.bind_current(manager, pending.command_control)
    )


async def _command_outcomes(
    manager: Any, pending: Pending, message: Any, scene_id: str | None
) -> list[MovementOutcome]:
    if not pending.command_outcomes or not _command_current(manager, pending, message, scene_id):
        return []
    binding = turn_controls.binding(pending.command_control)
    source = await manager.db.scalar(
        select(ChatMessage)
        .where(
            ChatMessage.id == binding.input_id,
            ChatMessage.session_id == manager.game_id,
            ChatMessage.role == "user",
        )
        .execution_options(populate_existing=True)
    )
    if (
        source is None
        or source.revision_id != binding.input_revision
        or sha256(source.content.encode()).hexdigest() != binding.input_hash
        or not _command_current(manager, pending, message, scene_id)
    ):
        return []
    return pending.command_outcomes


def _batch_size(pending: Pending) -> int:
    return max(pending.original_count, len(pending.proposals or []) + len(pending.command_outcomes))


def complete(
    manager: Any, proposals: list[Any], *, denied: set[str] | None = None, confirmed: bool = True
) -> None:
    pending = getattr(manager, "_pending_narrated_movement", None)
    if isinstance(pending, Pending) and not confirmed and proposals:
        reject(
            "movement",
            "narrated_movement.unconfirmed",
            "Movement extraction did not confirm the proposed changes.",
            proposals=proposals,
            source_context=pending.before,
            narration=pending.narration,
            player_message=pending.player_message,
            denied=denied,
        )
    if isinstance(pending, Pending):
        pending.proposals = deepcopy(proposals)
        pending.denied = frozenset(denied or ())
        pending.confirmed = confirmed


@step("movement.narration.commit")
async def finish(manager: Any, message: Any) -> list[str]:
    pending = getattr(manager, "_pending_narrated_movement", None)
    manager._pending_narrated_movement = None
    if not isinstance(pending, Pending):
        return []
    if pending.proposals is None:
        return (
            await _review(manager, message, [], [], pending=pending)
            if pending.command_outcomes
            else []
        )
    if not pending.confirmed:
        return await _review(manager, message, [], [], _unconfirmed(pending), pending=pending)
    if not pending.proposals and _batch_size(pending) <= MAX_MOVEMENTS:
        return await _review(manager, message, [], [], pending=pending)
    rows = await session_objects(manager.db, manager.state.session_id)
    current_context = await context(manager, rows) if pending.narration == message.content else None
    if pending.narration != message.content or pending.before != current_context:
        reject(
            "movement",
            "narrated_movement.stale_source",
            "The movement source state changed during extraction.",
            proposals=pending.proposals,
            source_context=pending.before,
            current_scene_id=manager.state.current_scene_id,
            narration=pending.narration,
            committed_narration=message.content,
            player_message=pending.player_message,
            denied=pending.denied,
            current_context=current_context,
        )
        return await _review(
            manager,
            message,
            [],
            ["The movement source state changed during extraction."],
            _unconfirmed(pending),
            pending=pending,
        )
    event, accepted, errors = _event(pending)
    applied = await TurnStateApplier(manager).apply_narrated_movement(event) if accepted else []
    if manager.state.current_scene_id != pending.before["scene_id"]:
        message.scene_id = manager.state.current_scene_id
        await follow_transition(manager)
    return [
        *applied,
        *await _review(
            manager,
            message,
            accepted,
            errors,
            pending.outcomes,
            pending=pending,
            scene_id=event.new_scene_id,
        ),
    ]


def _event(pending: Pending) -> tuple[GameEvent, list[dict], list[str]]:
    event, accepted, errors = GameEvent(), [], []
    pending.outcomes.clear()
    entries = pending.proposals or []
    if _batch_size(pending) > MAX_MOVEMENTS:
        reject(
            "movement",
            "narrated_movement.batch_limit",
            "Too many movement proposals; no movement in this batch was applied.",
            proposals=entries,
            source_context=pending.before,
            limit=MAX_MOVEMENTS,
        )
        return event, [], ["Too many movement proposals; no movement in this batch was applied."]
    counts = Counter(
        row["actor_id"].strip()
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
            outcome = receipt(proposal.model_dump(), pending.narration, "applied")
            if outcome is not None:
                pending.outcomes.append(outcome)
        except ValidationError as exc:
            reject(
                "movement",
                "narrated_movement.invalid_proposal",
                str(exc),
                proposal=raw,
                index=index,
                source_context=pending.before,
                narration=pending.narration,
                player_message=pending.player_message,
                denied=pending.denied,
                validation_errors=exc.errors(include_url=False),
            )
            errors.append(
                f"Movement proposal {index + 1}: Invalid movement fields or source reference."
            )
            outcome = receipt(raw, pending.narration, "unconfirmed")
            if outcome is not None:
                pending.outcomes.append(outcome)
        except ValueError as exc:
            reject(
                "movement",
                "narrated_movement.invalid_proposal",
                str(exc),
                proposal=raw,
                index=index,
                source_context=pending.before,
                narration=pending.narration,
                player_message=pending.player_message,
                denied=pending.denied,
            )
            errors.append(f"Movement proposal {index + 1}: {exc}")
            outcome = receipt(
                raw,
                pending.narration,
                "blocked" if isinstance(exc, MovementBlockedError) else "unconfirmed",
            )
            if outcome is not None:
                pending.outcomes.append(outcome)
    return event, accepted, errors


def _unconfirmed(pending: Pending) -> list[MovementOutcome]:
    if _batch_size(pending) > MAX_MOVEMENTS:
        return []
    return [
        outcome
        for raw in pending.proposals or []
        if (outcome := receipt(raw, pending.narration, "unconfirmed")) is not None
    ]


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


async def _review(
    manager: Any,
    message: Any,
    accepted: list[dict],
    errors: list[str],
    outcomes: list[MovementOutcome] | None = None,
    *,
    pending: Pending | None = None,
    scene_id: str | None = None,
) -> list[str]:
    from backend.engine.narrated_items.runtime import KEY

    command_outcomes = (
        await _command_outcomes(manager, pending, message, scene_id) if pending is not None else []
    )
    outcomes = command_outcomes + (outcomes or [])
    states = manager.state.entity_states or {}
    check = states.get(KEY)
    if isinstance(check, dict):
        audit = {
            "message_id": message.id,
            "revision_id": message.revision_id,
            "content_hash": sha256(message.content.encode()).hexdigest(),
            "accepted": accepted,
            "rejected": errors,
            "outcomes": [entry.model_dump(mode="json") for entry in outcomes or ()],
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
