"""Publish approved actor commands sequentially through their existing state owners."""

from copy import deepcopy
from dataclasses import replace
from typing import Any, Literal

from backend.engine.clothing.context import actor_records
from backend.engine.clothing.runtime import _store_actor
from backend.engine.clothing.visuals import session_objects
from backend.engine.gameplay.turn_state_applier import TurnStateApplier
from backend.engine.narrated_items.commands import transfer
from backend.engine.narrated_items.persistence import publish_command
from backend.engine.narrated_movement.context import context as movement_context
from backend.engine.npc_actions.contracts import (
    Adjust,
    ChangeState,
    Give,
    Move,
    PutDown,
    Request,
    Take,
    TakeOff,
    Use,
    Wear,
)
from backend.engine.npc_actions.preview import Draft, Scope
from backend.engine.physical_conditions.schema import KEY as CONDITIONS_KEY
from backend.engine.rule_engine import EntityMovement, GameEvent
from backend.engine.visual_novel.continuity import possession_snapshot


async def _fresh(manager: Any, scope: Scope) -> Scope:
    if manager.game_id != scope.session_id or manager.state.current_scene_id != scope.scene_id:
        raise ValueError("The command's scene or session changed.")
    if getattr(manager, "_vn_player_message_id", None) != scope.input_id:
        raise ValueError("The active input changed before command publication.")
    rows = await session_objects(manager.db, manager.game_id)
    actors = actor_records(manager, rows)
    if scope.actor_id not in actors:
        raise ValueError("The command actor is no longer present.")
    routes = await movement_context(manager, rows)
    permitted = routes.get("actors", {}).get(scope.actor_id, {}).get("allowed_destinations", [])
    return replace(
        scope,
        actors=actors,
        possessions=possession_snapshot(manager, rows),
        states=deepcopy(manager.state.entity_states or {}),
        destinations=frozenset(permitted),
    )


async def _transfer(manager: Any, scope: Scope, request: Take | Give | PutDown) -> None:
    operation: Literal["take", "give", "put_down"] = (
        "take" if isinstance(request, Take) else "give" if isinstance(request, Give) else "put_down"
    )
    changed, _, entry = transfer(
        scope.actors,
        scope.possessions,
        scope.actor_id,
        request.item_id,
        operation,
        detailed=scope.detailed,
        recipient_id=request.recipient_id if isinstance(request, Give) else None,
        position=request.position if isinstance(request, PutDown) else None,
    )
    await publish_command(manager, scope.actors, scope.possessions, changed, entry)


async def _apply(manager: Any, scope: Scope, request: Request, preview: Draft) -> None:
    if isinstance(request, (Take, Give, PutDown)):
        await _transfer(manager, scope, request)
        return
    if isinstance(request, Move):
        event = GameEvent(
            moved_entities=[
                EntityMovement(entity_id=scope.actor_id, to_scene_id=request.destination_scene_id)
            ]
        )
        await TurnStateApplier(manager).apply_narrated_movement(event)
        return
    actors, _, states = preview.working_copy()
    if isinstance(request, (Wear, TakeOff, Adjust)):
        current = deepcopy(manager.state.entity_states or {})
        _store_actor(manager, current, actors[scope.actor_id])
        manager.state.entity_states = current
        return
    if isinstance(request, (ChangeState, Use)):
        manager.state.entity_states = {
            **(manager.state.entity_states or {}),
            CONDITIONS_KEY: states[CONDITIONS_KEY],
        }
        return
    raise ValueError("The command has no authoritative owner operation.")


async def publish(manager: Any, draft: Draft) -> list[dict]:
    """A failed prerequisite stops dependent commands; successful earlier commands remain explicit."""
    if not draft.approved:
        return []
    if draft.published_results is not None:
        return deepcopy(draft.published_results)
    results = []
    blocked = False
    for index, request in enumerate(draft.requests):
        base = {"index": index, "tool": request.tool}
        if blocked:
            results.append({**base, "status": "skipped_dependency"})
            continue
        try:
            scope = await _fresh(manager, draft.scope)
            preview = Draft(scope, start_index=index)
            result = preview.execute(request)
        except ValueError as exc:
            blocked = True
            results.append({**base, "status": "blocked", "message": str(exc)[:320]})
            continue
        if result["status"] != "staged":
            blocked = True
            results.append({**base, **result})
            continue
        # Unexpected owner failures must reach turn recovery, never masquerade as
        # a safely blocked command after a partially changed transaction.
        await _apply(manager, scope, request, preview)
        results.append({**base, "status": "applied", "effect": result["effect"]})
    draft.published_results = deepcopy(results)
    return results
