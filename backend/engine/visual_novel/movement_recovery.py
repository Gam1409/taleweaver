"""Revalidate bounded VN recovery through the existing movement owner before applying it."""

import json
from collections import defaultdict
from types import SimpleNamespace
from typing import Any

from sqlalchemy import select

from backend.core.state_rejection_trace import reject
from backend.core.text_evidence import EvidenceSpan
from backend.engine.chpm.movement_authority import historical_action
from backend.engine.chpm.movement_feedback import read
from backend.engine.chpm.state import controls
from backend.engine.clothing.visuals import session_objects
from backend.engine.mutation_targets import TargetIndex
from backend.engine.narrated_movement.context import context
from backend.engine.narrated_movement.schema import MAX_MOVEMENTS, MovementProposal
from backend.engine.narrated_movement.validation import validate
from backend.engine.visual_novel.movement_sources import resolve
from backend.models.chat import ChatMessage
from backend.models.world_entity import WorldScene

NOTICE = "Some proposed movements need review; unconfirmed locations were preserved. Review Debug → State."


def _physical(update: Any) -> bool:
    return update.presence is not None or update.spatial_position is not None


def _group(rows: list[Any], index: TargetIndex) -> dict[str, list[Any]]:
    grouped = defaultdict(list)
    for row in rows:
        identifier = index.resolve(row.entity_id)
        if identifier is not None:
            grouped[identifier].append(row)
    return grouped


def _source_for(moves: list[Any], updates: list[Any]) -> Any:
    proofs = [getattr(row, "movement_source", None) for row in [*moves, *updates]]
    if not proofs or any(proof is None for proof in proofs):
        raise ValueError("NPC physical changes require a supplied movement source.")
    if any(proof != proofs[0] for proof in proofs):
        raise ValueError("One NPC's physical changes require one unambiguous source occurrence.")
    return proofs[0]


def _proposal(
    actor_id: str, moves: list[Any], updates: list[Any], passage: Any
) -> MovementProposal:
    if len(moves) > 1 or len(updates) > 1:
        raise ValueError("Multiple physical changes for one NPC are ambiguous.")
    destination = moves[0].to_scene_id if moves else None
    presence = updates[0].presence if updates else None
    return MovementProposal(
        actor_id=actor_id,
        destination_scene_id=destination,
        presence=presence or "present",
        basis="completed",
        evidence=passage.text,
        evidence_span=EvidenceSpan(start=passage.start, end=passage.end),
    )


async def _check_history(manager: Any, source: Any, passage: Any, actor: str, before: dict) -> None:
    if source.scene_id != before["scene_id"]:
        raise ValueError("Historical recovery belongs to a different source location.")
    message = await manager.db.get(ChatMessage, source.message_id)
    authority = historical_action(
        manager.state, actor, message, EvidenceSpan(start=passage.start, end=passage.end)
    )
    if authority == "blocked":
        raise ValueError(
            "A previously blocked movement cannot become a completed historical action."
        )
    if controls(manager.state, actor) and authority not in {"reviewed", "fallback"}:
        raise ValueError(
            "Historical recovery lacks this controlled NPC's source-time action owner."
        )
    outcomes = (*source.outcomes, *read(manager.state, message))
    if any(
        entry.actor_id == actor
        and entry.status == "blocked"
        and passage.start < entry.evidence_span.end
        and entry.evidence_span.start < passage.end
        for entry in outcomes
    ):
        raise ValueError(
            "A previously blocked movement cannot become a completed historical action."
        )


async def _check(
    manager: Any,
    actor: str,
    moves: list[Any],
    updates: list[Any],
    raw: tuple[list, list],
    before: dict,
) -> None:
    proof = _source_for(*raw)
    source, passage = await resolve(manager, proof)
    if source.scene_id != before["scene_id"]:
        raise ValueError("Movement source belongs to a different origin location.")
    expected = {
        "previous_narration": "completed",
        "current_player_action": "resolved_external_effect",
    }
    if proof.basis != expected[proof.kind]:
        raise ValueError("Movement source does not describe a completed permitted physical effect.")
    if proof.kind == "previous_narration":
        await _check_history(manager, source, passage, actor, before)
    proposal = _proposal(actor, moves, updates, passage)
    pending = SimpleNamespace(before=before, narration=source.text, denied=(), player_message="")
    # A local pose does not require map mobility; retain the existing stationary-NPC contract.
    local_pose = proposal.destination_scene_id in (None, before["scene_id"]) and all(
        row.presence is None for row in updates
    )
    if local_pose and actor in before["actors"]:
        pending.before = {
            **before,
            "actors": {**before["actors"], actor: {**before["actors"][actor], "can_move": True}},
        }
    validate(proposal, pending)


def _retain(event: Any, actor: str) -> None:
    event.moved_entities = [row for row in event.moved_entities or [] if row.entity_id != actor]
    for update in event.updated_entities or []:
        if update.entity_id == actor:
            update.presence = None
            update.spatial_position = None
            update.notes = None


def _story_actor(manager: Any, event: Any) -> str | None:
    beat = getattr(manager, "_vn_story_beat", None)
    identifier = getattr(beat, "npc_id", None)
    if (
        beat is not None
        and isinstance(identifier, str)
        and any(
            row.entity_id == identifier and row.to_scene_id == beat.destination_id
            for row in event.moved_entities or []
        )
    ):
        return identifier
    return None


def _check_story(actor: str, moves: list[Any], updates: list[Any], before: dict) -> None:
    entry = before["actors"].get(actor)
    if len(moves) != 1 or updates or not entry or not entry["can_move"]:
        raise ValueError("The staged departure no longer has an available moving actor.")
    if moves[0].to_scene_id not in entry["allowed_destinations"]:
        raise ValueError("The staged departure no longer has an open permitted adjacent route.")


async def _destinations(manager: Any) -> TargetIndex:
    rows = await manager.db.scalars(
        select(WorldScene).where(WorldScene.session_id == manager.game_id)
    )
    return TargetIndex([{"id": row.id, "name": row.label} for row in rows])


def _canonical_moves(moves: list[Any], destinations: TargetIndex) -> None:
    for move in moves:
        if move.to_scene_id is None:
            continue
        destination = destinations.resolve(move.to_scene_id)
        if destination is None:
            raise ValueError("The destination does not identify a session location.")
        move.to_scene_id = destination


async def _resolve_actor(
    manager: Any,
    event: Any,
    actor: str,
    moves: list[Any],
    updates: list[Any],
    raw: tuple[list, list],
    before: dict,
    destinations: TargetIndex,
    batch_size: int,
) -> None:
    if batch_size > MAX_MOVEMENTS:
        raise ValueError("Too many NPC physical proposals; this batch requires review.")
    _canonical_moves(moves, destinations)
    if actor == _story_actor(manager, event):
        _check_story(actor, moves, updates, before)
        return
    if raw[0] and not moves:
        raise ValueError("The movement was rejected by the existing world guardrails.")
    await _check(manager, actor, moves, updates, raw, before)


async def resolve_event(manager: Any, event: Any) -> list[str]:
    """Keep accepted mutations in the existing event; never manufacture a past success."""
    manager._vn_movement_resolution = ""
    rows = await session_objects(manager.db, manager.state.session_id)
    index = TargetIndex(
        [{"id": row.id, "name": row.name} for row in rows if row.entity_type == "NPC"]
    )
    moves = _group(event.moved_entities or [], index)
    updates = _group([row for row in event.updated_entities or [] if _physical(row)], index)
    proposal = getattr(manager, "_vn_movement_proposal", None)
    raw_moves = _group(getattr(proposal, "moved_entities", None) or [], index)
    raw_updates = _group(
        [row for row in getattr(proposal, "updated_entities", None) or [] if _physical(row)], index
    )
    before = await context(manager, rows, exit_updates=event.updated_exits or [])
    destinations = await _destinations(manager)
    rejected = []
    actors = sorted(set(moves) | set(updates) | set(raw_moves) | set(raw_updates))
    for actor in actors:
        try:
            await _resolve_actor(
                manager,
                event,
                actor,
                moves.get(actor, []),
                updates.get(actor, []),
                (raw_moves.get(actor, []), raw_updates.get(actor, [])),
                before,
                destinations,
                len(actors),
            )
        except ValueError as exc:
            reject(
                "movement",
                "vn_movement.retained",
                str(exc),
                actor_id=actor,
                proposal={"moves": raw_moves.get(actor, []), "updates": raw_updates.get(actor, [])},
            )
            _retain(event, actor)
            rejected.append(actor)
    if not rejected:
        return []
    manager._vn_movement_resolution = (
        "MOVEMENT REVIEW: The following NPC physical proposals were not applied: "
        + json.dumps(rejected)
        + ". Current canonical locations and presence are authoritative. Unconfirmed is not a "
        "fictional failure: do not invent a failed attempt, obstacle, departure or return. "
        "Do not repeat the unsupported physical proposal as a completed world fact."
    )
    await manager._save_chat_message("system", NOTICE)
    return [NOTICE]
