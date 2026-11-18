"""Bind preliminary player item operations to existing sources and custody owners."""

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

from backend.engine import turn_controls
from backend.engine.npc_actions import control, prepass
from backend.engine.rule_engine import WorldEntityUpdate
from backend.engine.visual_novel.continuity import PLAYER, SCENE, Possessions
from backend.engine.visual_novel.movement_contracts import MovementSource
from backend.engine.visual_novel.movement_sources import Source, current_input, resolve
from backend.engine.visual_novel.player_item_contracts import MAX_ACTIONS, PlayerItemAction

WARDROBE = frozenset({"wear", "remove", "adjust", "acquire_garment"})


@dataclass(frozen=True)
class Scope:
    enabled: bool
    actors: tuple[str, ...]
    source_scene: str


@dataclass
class Plan:
    """Transient host validation; the normal event owner still has to apply its final delta."""

    scope: Scope
    operation: turn_controls.Operation
    actions: tuple[PlayerItemAction, ...]
    destinations: dict[str, str]
    removed: frozenset[str]
    source_text: str = ""
    previous_owners: dict[str, str] = field(default_factory=dict)
    effect_operations: dict[str, turn_controls.Operation] = field(default_factory=dict)
    deferred_ids: frozenset[str] = frozenset()
    deferred_operation: turn_controls.Operation | None = None
    error: ValueError | None = None
    outcomes: list[dict] | None = None


def capture(manager: Any) -> Scope:
    selected = prepass.context(manager.state)
    return Scope(
        prepass.enabled(manager.state),
        tuple(selected.get("controlled_actor_ids", ())),
        manager.state.current_scene_id,
    )


def _current(manager: Any, scope: Scope, captured: Mapping) -> None:
    current = capture(manager)
    if (current.enabled, current.actors) != (
        scope.enabled,
        scope.actors,
    ) or not turn_controls.bind_current(manager, captured, "preliminary_items"):
        raise control.CommandRejectedError("stale")


async def _source(manager: Any, action: PlayerItemAction, scope: Scope, captured: Mapping) -> None:
    proof = MovementSource(
        kind="current_player_action", passage_id=action.passage_id, basis="resolved_external_effect"
    )
    # Legacy source DTOs normalize strings; new handles must still match exactly.
    if proof.passage_id != action.passage_id:
        raise control.CommandRejectedError("preliminary_item_rejected")
    source, _ = await resolve(manager, proof)
    _current(manager, scope, captured)
    if source.role != "user" or source.scene_id != scope.source_scene:
        raise control.CommandRejectedError("preliminary_item_rejected")


def _destination(action: PlayerItemAction, working: dict[str, str], snapshot: Possessions) -> str:
    owner = working.get(str(action.item_id))
    if owner is None:
        raise control.CommandRejectedError("preliminary_item_rejected")
    if action.operation == "take":
        if owner == PLAYER or action.target_id is not None:
            raise control.CommandRejectedError("preliminary_item_rejected")
        return PLAYER
    if action.operation == "destroy":
        if action.target_id is not None:
            raise control.CommandRejectedError("preliminary_item_rejected")
        return ""
    if owner != PLAYER:
        raise control.CommandRejectedError("preliminary_item_rejected")
    if action.operation == "give":
        if action.target_id not in snapshot.npcs and action.target_id not in snapshot.containers:
            raise control.CommandRejectedError("preliminary_item_rejected")
        return str(action.target_id)
    if action.target_id is not None:
        raise control.CommandRejectedError("preliminary_item_rejected")
    return SCENE if action.operation == "drop" else ""


def _resolve(
    actions: tuple[PlayerItemAction, ...], snapshot: Possessions
) -> tuple[dict, frozenset]:
    if len(actions) > MAX_ACTIONS:
        raise control.CommandRejectedError("preliminary_item_rejected")
    working = dict(snapshot.owners)
    removed: set[str] = set()
    for action in actions:
        if action.performer_id != PLAYER or action.basis != "performed":
            raise control.CommandRejectedError("preliminary_item_rejected")
        if action.operation in WARDROBE:
            _wardrobe_target(action, working, snapshot)
            continue
        destination = _destination(action, working, snapshot)
        if destination:
            working[str(action.item_id)] = destination
        else:
            removed.add(str(action.item_id))
            working.pop(str(action.item_id))
    destinations = {
        identifier: owner
        for identifier, owner in working.items()
        if owner != snapshot.owners.get(identifier)
    }
    return destinations, frozenset(removed)


def _wardrobe_target(action: PlayerItemAction, working: dict, snapshot: Possessions) -> None:
    if action.target_id != PLAYER and action.target_id not in snapshot.npcs:
        raise control.CommandRejectedError("preliminary_item_rejected")
    if action.operation != "acquire_garment" and working.get(action.item_id) != action.target_id:
        raise control.CommandRejectedError("preliminary_item_rejected")


def _creation(action: PlayerItemAction, proposal: Any) -> None:
    creations = getattr(proposal, "garment_creations", ()) or ()
    if (
        action.creation_ref is None
        or action.creation_ref >= len(creations)
        or creations[action.creation_ref].actor_id != action.target_id
    ):
        raise control.CommandRejectedError("preliminary_item_rejected")


def _attribute_actions(
    plan: Plan, proposed: tuple[PlayerItemAction, ...], snapshot: Possessions
) -> None:
    performers = {None, PLAYER, *snapshot.npcs}
    if any(action.performer_id not in performers for action in proposed):
        raise control.CommandRejectedError("preliminary_item_rejected")
    # A user source identifies who supplied the text, not who performed its action.
    plan.actions = tuple(
        action
        for action in proposed
        if action.performer_id == PLAYER and action.basis == "performed"
    )
    deferred = [action for action in proposed if action not in plan.actions]
    if deferred:
        plan.deferred_ids = frozenset(
            action.item_id
            for action in deferred
            if action.item_id is not None and action.item_id in snapshot.items
        )
        plan.deferred_operation = turn_controls.operation(
            plan.operation.model_dump(), "pending_item_proposal", actor_id=PLAYER
        )


async def prepare(
    manager: Any, proposal: Any, rows: list[Any], *, scope: Scope, captured: Mapping
) -> Plan | None:
    """Validate references after awaits; completion labels alone grant no custody authority."""
    _current(manager, scope, captured)
    if not scope.enabled:
        return None
    from backend.engine.visual_novel.continuity import possession_snapshot

    plan = Plan(
        scope,
        turn_controls.operation(captured, "player_item_plan", actor_id=PLAYER),
        (),
        {},
        frozenset(),
    )
    try:
        source = getattr(manager, "_vn_movement_sources", {}).get("current_player_action")
        if not isinstance(source, Source):
            raise control.CommandRejectedError("preliminary_item_rejected")
        plan.source_text = source.text
        raw = getattr(proposal, "player_item_actions", ()) or ()
        if len(raw) > MAX_ACTIONS:
            raise control.CommandRejectedError("preliminary_item_rejected")
        proposed = tuple(map(PlayerItemAction.model_validate, raw))
        snapshot = possession_snapshot(manager, rows)
        for action in proposed:
            await _source(manager, action, scope, captured)
        _attribute_actions(plan, proposed, snapshot)
        for action in plan.actions:
            if action.operation == "acquire_garment":
                _creation(action, proposal)
        plan.destinations, plan.removed = _resolve(plan.actions, snapshot)
        identifiers = {str(action.item_id) for action in plan.actions if action.item_id}
        plan.previous_owners = {key: snapshot.owners[key] for key in identifiers}
        plan.effect_operations = {
            key: turn_controls.operation(captured, "player_item_custody", actor_id=PLAYER)
            for key in sorted(set(plan.destinations) | plan.removed)
        }
    except ValueError as error:
        if isinstance(error, control.CommandRejectedError) and error.code == "stale":
            raise
        plan.error = error
    return plan


def assisted(plan: Any, change: Any, *, creation_ref: int | None = None) -> bool:
    if not isinstance(plan, Plan) or plan.error or change.agency != "consented_assistance":
        return False
    kind = "acquire_garment" if creation_ref is not None else change.operation
    return any(
        action.operation == kind
        and action.target_id == change.actor_id
        and (
            action.creation_ref == creation_ref
            if creation_ref is not None
            else action.item_id == change.item_id
        )
        for action in plan.actions
    )


def acquired(plan: Any, change: Any, *, creation_ref: int | None) -> bool:
    """Read a linked performed player acquisition; this grants no NPC agency or mutation."""
    if not isinstance(plan, Plan) or plan.error or creation_ref is None:
        return False
    return any(
        action.performer_id == PLAYER
        and action.basis == "performed"
        and action.operation == "acquire_garment"
        and action.target_id == change.actor_id
        and action.creation_ref == creation_ref
        for action in plan.actions
    )


def _check_items(plan: Plan, snapshot: Possessions) -> None:
    # Custody/access are preconditions. Descriptive metadata is hydrated from the
    # current owner, so an image update cannot invalidate an otherwise legal action.
    if any(
        snapshot.owners.get(key) != owner or key not in snapshot.items
        for key, owner in plan.previous_owners.items()
    ):
        raise control.CommandRejectedError("preliminary_item_rejected")


def _deferred(result: Any, snapshot: Possessions, planned: dict) -> frozenset[str]:
    requested = [
        *((item.id, PLAYER) for item in result.new_inventory_items or []),
        *((item.id, SCENE) for item in result.spawned_items or []),
        *(
            (item.id, row.entity_id)
            for row in result.updated_entities or []
            for item in row.inventory or []
        ),
        *((identifier, None) for identifier in result.deleted_entities or []),
    ]
    deferred = {
        key
        for key, owner in requested
        if key in snapshot.owners
        and snapshot.owners[key] != owner
        and planned.get(key, snapshot.owners[key]) != owner
    }
    deferred.update(
        key
        for key in result.removed_inventory_item_ids or []
        if snapshot.owners.get(key) == PLAYER and planned.get(key, PLAYER) == PLAYER
    )
    return frozenset(deferred)


def _approved(manager: Any, snapshot: Possessions, plan: Plan | None) -> tuple[dict, frozenset]:
    if plan is None:
        return {}, frozenset()
    _current(manager, plan.scope, plan.operation.model_dump())
    if plan.error:
        raise plan.error
    _check_items(plan, snapshot)
    destinations, removed = _resolve(plan.actions, snapshot)
    if destinations != plan.destinations or removed != plan.removed:
        raise control.CommandRejectedError("preliminary_item_rejected")
    return destinations, removed


def constrain(manager: Any, result: Any, snapshot: Possessions, plan: Plan | None) -> bool:
    """Raw final inventories never independently authorize active preliminary custody changes."""
    if not prepass.enabled(manager.state):
        return False
    destinations, removed = _approved(manager, snapshot, plan)
    deferred = _deferred(result, snapshot, {**destinations, **dict.fromkeys(removed)})
    if plan is not None:
        deferred |= plan.deferred_ids
    if deferred or (plan is not None and plan.deferred_operation is not None):
        # Render the phase note from a host flag, not from an invented failure in prose.
        result.narrative_description = "Some preliminary item proposals await their responsible actor; use canonical state and applied outcomes."
        if plan is not None:
            plan.deferred_ids = deferred
            if plan.deferred_operation is None:
                plan.deferred_operation = turn_controls.operation(
                    plan.operation.model_dump(), "pending_item_proposal", actor_id=PLAYER
                )
    result.new_inventory_items = []
    result.removed_inventory_item_ids = []
    result.spawned_items = []
    result.deleted_entities = sorted(removed)
    result.removed_inventory_item_ids = sorted(
        identifier
        for identifier, owner in snapshot.owners.items()
        if owner == PLAYER
        and (identifier in removed or destinations.get(identifier, PLAYER) != PLAYER)
    )
    updates = {row.entity_id: row for row in result.updated_entities or []}
    for row in updates.values():
        row.inventory = None
    from backend.engine.visual_novel.continuity import CanonicalInventoryItem

    for identifier, owner in destinations.items():
        item = CanonicalInventoryItem.model_validate(deepcopy(snapshot.items[identifier]))
        if owner == PLAYER:
            result.new_inventory_items.append(item)
        elif owner == SCENE:
            result.spawned_items.append(item)
        else:
            update = updates.setdefault(owner, WorldEntityUpdate(entity_id=owner, inventory=[]))
            update.inventory = [*(update.inventory or []), item]
    result.updated_entities = list(updates.values())
    return True


def attach(event: Any, plan: Plan | None) -> None:
    if plan is not None:
        event._vn_player_item_plan = plan


async def validate_application(manager: Any, event: Any) -> None:
    plan = getattr(event, "_vn_player_item_plan", None)
    if not isinstance(plan, Plan) or plan.error:
        return
    captured = plan.operation.model_dump()
    _current(manager, plan.scope, captured)
    if manager.state.current_scene_id != plan.scope.source_scene:
        raise control.CommandRejectedError("stale")
    # Even an empty plan belongs to the saved input. An edit during inference
    # invalidates the old event, including unrelated fields of that proposal.
    await current_input(manager, plan.source_text)
    _current(manager, plan.scope, captured)
    from backend.engine.clothing.visuals import session_objects
    from backend.engine.visual_novel.continuity import possession_snapshot

    rows = await session_objects(manager.db, manager.game_id)
    _current(manager, plan.scope, captured)
    _check_items(plan, possession_snapshot(manager, rows))


def complete(
    event: Any, destinations: dict[str, str], removed: set[str], actual: dict[str, set[str]]
) -> None:
    """Called only after the canonical custody owner applied the guardrail-filtered event."""
    plan = getattr(event, "_vn_player_item_plan", None)
    if not isinstance(plan, Plan) or plan.error:
        return
    if plan.outcomes is not None:
        return
    plan.outcomes = []
    if plan.deferred_operation is not None:
        plan.outcomes.append(
            control.result(
                plan.deferred_operation,
                "deferred",
                reason_code="preliminary_item_deferred",
                parent_operation_id=plan.operation.operation_id,
                item_ids=sorted(plan.deferred_ids),
            )
        )
    final = {**plan.destinations, **dict.fromkeys(plan.removed, None)}
    for identifier, owner in final.items():
        applied = (
            destinations.get(identifier) == owner and actual.get(identifier) == {owner}
            if owner is not None
            else identifier in removed and not actual.get(identifier)
        )
        operation = plan.effect_operations[identifier]
        plan.outcomes.append(
            control.result(
                operation,
                "applied" if applied else "blocked",
                parent_operation_id=plan.operation.operation_id,
                item_id=identifier,
                **(
                    {"effect": {"item_id": identifier, "destination_owner": owner}}
                    if applied
                    else {"reason_code": "preliminary_item_rejected"}
                ),
            )
        )


def outcome(event: Any) -> list[dict]:
    plan = getattr(event, "_vn_player_item_plan", None)
    return (plan.outcomes or []) if isinstance(plan, Plan) else []
