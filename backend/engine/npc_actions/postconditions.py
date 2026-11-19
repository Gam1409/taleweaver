"""Verify selected owner writes on the active turn before issuing their success receipts."""

from typing import Any

from backend.core.state_rejection_trace import reject
from backend.engine import turn_controls
from backend.engine.clothing.context import actor_records
from backend.engine.clothing.profiles import load_profile, owned_items
from backend.engine.clothing.projection import item_wear_state
from backend.engine.clothing.visuals import session_objects
from backend.engine.npc_actions.contracts import (
    Adjust,
    Approach,
    ChangeState,
    Give,
    Move,
    Pose,
    PutDown,
    Request,
    Take,
    TakeOff,
    Use,
    Wear,
)
from backend.engine.npc_actions.preview import Scope
from backend.engine.npc_actions.property_postconditions import verify as verify_property
from backend.engine.scene_staging.state import retained
from backend.engine.visual_novel.continuity import SCENE, possession_snapshot


class PostconditionViolationError(RuntimeError):
    """The host wrote an inconsistent result; the enclosing turn must roll back."""


def _current(manager: Any, scope: Scope) -> None:
    if (
        scope.session_id != manager.game_id
        or scope.scene_id != manager.state.current_scene_id
        or not turn_controls.bind_current(
            manager, scope.control, "npc_command_publication", observation=scope.observation
        )
    ):
        raise turn_controls.ControlBindingError(
            "The owner verification belongs to an inactive publication."
        )


def _pose(
    manager: Any, scope: Scope, effect: dict, operation: turn_controls.Operation
) -> str | None:
    record = retained(manager.state, list(scope.cast)).get(scope.actor_id, {})
    # Explicitly clearing an unknown posture removes its row. The current command
    # stamp distinguishes that successful clear from simply finding no actor.
    if record.get("command", {}).get("command_id") != operation.command_id:
        return "pose_source"
    if record.get("posture", {}).get("value", "unknown") != effect["posture"]:
        return "posture"
    if "placement" not in effect:
        return None
    expected, placement = effect["placement"], record.get("placement")
    if expected is None:
        return "placement" if placement is not None else None
    if not placement:
        return "placement"
    # Staging preserves a display label for a prop; identity is stored separately.
    target_field = "target_id" if expected["target_kind"] == "scene_object" else "target"
    matches = all(placement.get(key) == expected[key] for key in ("relation", "target_kind"))
    return None if matches and placement.get(target_field) == expected["target"] else "placement"


def _wear(actor: dict, request: Wear | TakeOff | Adjust, effect: dict) -> str | None:
    state = item_wear_state(
        actor["visual_profile"],
        actor["resolved_inventory"],
        request.item_id,
        equipment=actor["equipment"],
    )
    if isinstance(request, TakeOff):
        return "wear" if state != "carried" else None
    profile = load_profile(actor["visual_profile"])
    worn = (
        next((row for row in profile.worn if row.item_id == request.item_id), None)
        if profile
        else None
    )
    if state != "worn" or worn is None or worn.attachment_slot is not None:
        return "wear"
    return "coverage" if set(worn.uncovered_regions) != set(effect["uncovered_regions"]) else None


def _transfer(
    manager: Any, rows: list, source: dict, request: Take | Give | PutDown, effect: dict
) -> str | None:
    if isinstance(request, (Give, PutDown)) and request.item_id in owned_items(
        source["inventory"], equipment=source["equipment"]
    ):
        # The canonical projection can hide a donor copy behind a recipient's higher priority.
        return "custody"
    row = next(
        (item for item in rows if item.id == request.item_id and item.entity_type == "OBJECT"), None
    )
    loose = effect["destination_owner"] == SCENE
    if row is None:
        # Inline inventory entries need a world row only when placed on the ground.
        return "placement" if loose else None
    overlay = (manager.state.entity_states or {}).get(request.item_id, {})
    if (
        row.is_in_inventory != (not loose)
        or overlay.get("is_in_inventory", row.is_in_inventory) != (not loose)
        or row.current_scene_id != manager.state.current_scene_id
    ):
        return "custody"
    position = effect.get("spatial_position")
    if (
        row.spatial_position != position
        or overlay.get("spatial_position", row.spatial_position) != position
    ):
        return "placement"
    return None


async def _item(
    manager: Any,
    scope: Scope,
    request: Take | Give | PutDown | Wear | TakeOff | Adjust,
    effect: dict,
) -> str | None:
    rows = await session_objects(manager.db, manager.game_id)
    _current(manager, scope)
    snapshot = possession_snapshot(manager, rows)
    if snapshot.owners.get(request.item_id) != effect.get("destination_owner", scope.actor_id):
        return "custody"
    actor = actor_records(manager, rows).get(scope.actor_id)
    if actor is None:
        return "custody"
    if isinstance(request, (Wear, TakeOff, Adjust)):
        return _wear(actor, request, effect)
    return _transfer(manager, rows, actor, request, effect)


async def _move(manager: Any, scope: Scope, request: Move, effect: dict) -> str | None:
    rows = await session_objects(manager.db, manager.game_id)
    _current(manager, scope)
    actor = next(
        (row for row in rows if row.id == scope.actor_id and row.entity_type == "NPC"), None
    )
    overlay = (manager.state.entity_states or {}).get(scope.actor_id, {})
    if actor is None or not isinstance(overlay, dict):
        return "movement_actor"
    if (
        effect.get("destination_scene_id") != request.destination_scene_id
        or overlay.get("current_scene_id", actor.current_scene_id) != request.destination_scene_id
    ):
        return "movement_location"
    if overlay.get("presence", getattr(actor, "presence", "present")) != "present":
        return "movement_presence"
    if overlay.get("spatial_position", actor.spatial_position) is not None:
        return "movement_position"
    if int(manager.state.in_game_time or 0) != scope.minute:
        return "movement_clock"
    return None


async def _property(
    manager: Any,
    scope: Scope,
    request: ChangeState | Use,
    effect: dict,
    operation: turn_controls.Operation,
) -> str | None:
    rows = await session_objects(manager.db, manager.game_id)
    _current(manager, scope)
    if possession_snapshot(manager, rows).owners.get(request.item_id) != scope.actor_id:
        return "property_custody"
    return verify_property(manager, scope, request, effect, operation)


async def verify(
    manager: Any, scope: Scope, request: Request, effect: dict, operation: turn_controls.Operation
) -> None:
    """Inspect only fields covered by this preview; previous/subsequent steps have their own receipts."""
    _current(manager, scope)
    if isinstance(request, (Take, Give, PutDown, Wear, TakeOff, Adjust)):
        issue = await _item(manager, scope, request, effect)
    elif isinstance(request, (Pose, Approach)):
        issue = _pose(manager, scope, effect, operation)
    elif isinstance(request, Move):
        issue = await _move(manager, scope, request, effect)
    elif isinstance(request, (ChangeState, Use)):
        issue = await _property(manager, scope, request, effect, operation)
    else:
        return
    if issue is None:
        return
    # Private operands, other actors' state and item descriptions stay out of this diagnostic.
    message = "A published NPC operation did not establish its expected owner state."
    reject(
        "npc_actions",
        "postcondition_violation",
        message,
        attempt_id=operation.attempt_id,
        operation_id=operation.operation_id,
        tool=operation.tool,
        field=issue,
    )
    raise PostconditionViolationError(message)
