"""Publish approved actor commands sequentially through their existing state owners."""

from copy import deepcopy
from dataclasses import replace
from typing import Any, Literal

from backend.engine import turn_controls
from backend.engine.clothing.context import actor_records
from backend.engine.clothing.runtime import _store_actor
from backend.engine.clothing.visuals import detailed_for_state, session_objects
from backend.engine.gameplay.turn_state_applier import TurnStateApplier
from backend.engine.narrated_items.commands import carried_after, transfer
from backend.engine.narrated_items.persistence import publish_command
from backend.engine.narrated_movement.context import context as movement_context
from backend.engine.npc_actions import control, postconditions
from backend.engine.npc_actions.contracts import (
    Adjust,
    Approach,
    ChangeState,
    Give,
    Interact,
    Move,
    Pose,
    PutDown,
    Request,
    Take,
    TakeOff,
    Use,
    Wear,
)
from backend.engine.npc_actions.preview import Draft, Scope, operation_identity
from backend.engine.physical_conditions.schema import KEY as CONDITIONS_KEY
from backend.engine.rule_engine import EntityMovement, GameEvent
from backend.engine.scene_staging.shared import _cast
from backend.engine.scene_staging.state import KEY as STAGING_KEY
from backend.engine.visual_novel.config import read_settings
from backend.engine.visual_novel.continuity import possession_snapshot


async def _fresh(manager: Any, scope: Scope) -> Scope:
    from backend.engine.chpm.observable_state import project

    if not turn_controls.bind_current(manager, scope.control, observation=scope.observation):
        raise control.CommandRejectedError("stale")
    if manager.game_id != scope.session_id or manager.state.current_scene_id != scope.scene_id:
        raise control.CommandRejectedError("stale")
    if getattr(manager, "_vn_player_message_id", None) != scope.input_id:
        raise control.CommandRejectedError("stale")
    rows = await session_objects(manager.db, manager.game_id)
    actors = actor_records(manager, rows)
    if scope.actor_id not in actors:
        raise ValueError("The command actor is no longer present.")
    routes = await movement_context(manager, rows)
    permitted = routes.get("actors", {}).get(scope.actor_id, {}).get("allowed_destinations", [])
    visible = (
        project(manager, rows, scope.actor_id, scope.observation)
        if scope.observation is not None
        else None
    )
    if not turn_controls.bind_current(manager, scope.control, observation=scope.observation):
        raise control.CommandRejectedError("stale")
    return replace(
        scope,
        actors=actors,
        possessions=possession_snapshot(manager, rows),
        states=deepcopy(manager.state.entity_states or {}),
        destinations=frozenset(permitted),
        detailed=detailed_for_state(manager.state),
        minute=int(manager.state.in_game_time or 0),
        accessible_ids=scope.accessible_ids & frozenset(visible.entities)
        if visible
        else scope.accessible_ids,
        cast=tuple(_cast(manager, actors, rows)),
        staging_enabled=read_settings(manager.state).scene_staging,
        scene_objects={
            key: row["name"][:120]
            for key, row in visible.entities.items()
            if row["kind"] == "item" and row.get("owner_id") == "__scene__"
        }
        if visible
        else scope.scene_objects,
        control=turn_controls.scope(
            manager, "npc_command_publication", observation=scope.observation
        ),
    )


async def _transfer(
    manager: Any, scope: Scope, request: Take | Give | PutDown, prior_receipts: tuple[dict, ...]
) -> None:
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
        carried_item_ids=carried_after(scope.actor_id, prior_receipts),
    )
    await publish_command(manager, scope.actors, scope.possessions, changed, entry)


async def _apply(manager: Any, scope: Scope, request: Request, preview: Draft) -> None:
    if not turn_controls.bind_current(manager, scope.control, observation=scope.observation):
        raise turn_controls.ControlBindingError(
            "The command publication belongs to an inactive attempt."
        )
    if isinstance(request, Interact):
        return
    if isinstance(request, (Take, Give, PutDown)):
        await _transfer(manager, scope, request, preview.prior_receipts)
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
    if isinstance(request, (Pose, Approach)):
        manager.state.entity_states = {
            **(manager.state.entity_states or {}),
            STAGING_KEY: states[STAGING_KEY],
        }
        return
    raise ValueError("The command has no authoritative owner operation.")


async def publish(manager: Any, draft: Draft, *, verify_postconditions: bool = False) -> list[dict]:
    """A failed prerequisite stops dependent commands; successful earlier commands remain explicit."""
    if not draft.approved:
        return []
    if not turn_controls.bind_current(
        manager, draft.scope.control, observation=draft.scope.observation
    ):
        return rejected_results(draft, "stale")
    if draft.published_results is not None:
        return deepcopy(draft.published_results)
    results: list[dict] = []
    blocked = False
    operations = {operation.command_id: operation for operation in draft.operations}
    for index, request in enumerate(draft.requests):
        identity, _ = operation_identity(draft.scope, request, draft.start_index + index)
        operation = operations.get(identity)
        if operation is None or operation.tool != request.tool:
            raise control.CommandRejectedError("invalid_operation")
        operation = operation.model_copy(update={"phase": "npc_command_publication"})
        if blocked:
            results.append(
                control.result(
                    operation, "skipped_dependency", index=index, reason_code="skipped_dependency"
                )
            )
            continue
        try:
            scope = await _fresh(manager, draft.scope)
            operation = operation.model_copy(
                update={"state_revision": scope.control["state_revision"]}
            )
            preview = Draft(
                scope,
                start_index=draft.start_index + index,
                prior_receipts=tuple(
                    row["effect"] for row in results if row["status"] == "applied"
                ),
            )
            result = preview.execute(request, operation=operation)
        except ValueError as exc:
            blocked = True
            results.append(control.owner_failure(operation, exc, index=index))
            continue
        if result["status"] != "staged":
            blocked = True
            results.append({**result, "index": index, "status": "blocked"})
            continue
        # Unexpected owner failures must reach turn recovery, never masquerade as
        # a safely blocked command after a partially changed transaction.
        await _apply(manager, scope, request, preview)
        if verify_postconditions:
            await postconditions.verify(manager, scope, request, result["effect"], operation)
        results.append(
            control.result(
                operation,
                "attempted" if isinstance(request, Interact) else "applied",
                index=index,
                effect=result["effect"],
                state_revision_before=scope.control["state_revision"],
                state_revision_after=turn_controls.state_revision(manager),
            )
        )
    draft.published_results = deepcopy(results)
    return results


def rejected_results(draft: Draft, code: str) -> list[dict]:
    return [
        control.result(
            operation.model_copy(update={"phase": "npc_command_publication"}),
            "stale",
            index=index,
            reason_code=code,
        )
        for index, operation in enumerate(draft.operations)
    ]
