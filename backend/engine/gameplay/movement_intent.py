"""One grounded check for player travel, including omitted group-motion proposals."""

from typing import Any

from backend.engine.gameplay.scene_transition_intent import confirm_scene_transition
from backend.engine.mutation_targets import TargetIndex
from backend.engine.npc_presence import physically_present


def _open_destinations(intent: Any, exits: list[dict]) -> set[str]:
    return {
        str(exit.get("to_scene_id") or "").strip()
        for exit in exits
        if not exit.get("is_locked")
        or any(
            update.to_scene_id == exit.get("to_scene_id") and not update.is_locked
            for update in (getattr(intent, "updated_exits", None) or [])
        )
    } - {""}


def _companion_targets(
    manager: Any, intent: Any, entities: list[Any], places: TargetIndex
) -> dict[str, str]:
    state = manager.state
    available = []
    for actor in entities:
        override = (state.entity_states or {}).get(actor.id) or {}
        if (
            actor.entity_type == "NPC"
            and override.get("current_scene_id", actor.current_scene_id) == state.current_scene_id
            and not override.get("is_hidden", actor.is_hidden)
            and physically_present(actor, state)
        ):
            available.append({"id": actor.id, "name": actor.name})
    actors = TargetIndex(available)
    targets = {}
    for move in intent.moved_entities or []:
        actor_id = actors.resolve(move.entity_id)
        destination = places.resolve(move.to_scene_id)
        if actor_id and destination and destination != state.current_scene_id:
            targets[actor_id] = destination
    return targets


async def confirm_player_movement(
    manager: Any,
    intent: Any,
    *,
    user_msg: str,
    scenes: list[dict],
    exits: list[dict],
    entities: list[Any],
    history: list[dict],
) -> None:
    """NPC travel supplies a candidate, never proof that the player moved with them."""
    manager._group_movement_resolution = ""
    places = TargetIndex([{"id": row["id"], "name": row.get("label")} for row in scenes])
    allowed = _open_destinations(intent, exits)
    companions = _companion_targets(manager, intent, entities, places)
    proposed = bool(intent.new_scene_id)
    destination = places.resolve(intent.new_scene_id)
    if destination is None:
        candidates = set(companions.values()) & allowed
        destination = next(iter(candidates)) if len(candidates) == 1 else None
    if destination is None or destination not in allowed:
        intent.new_scene_id = None
        intent.exit_label = None
        if proposed:
            _keep_companions(manager, intent, entities, companions, destination)
        return
    confirmed = await confirm_scene_transition(
        manager.adventure_gen.classify_short_intent,
        user_msg=user_msg,
        target_scene_id=destination,
        scenes=scenes,
        exits=exits,
        history=history,
    )
    intent.new_scene_id = destination if confirmed else None
    if confirmed:
        return
    intent.exit_label = None
    if not proposed:
        return  # An intentional NPC-only departure remains valid.
    _keep_companions(manager, intent, entities, companions, destination)


def _keep_companions(
    manager: Any,
    intent: Any,
    entities: list[Any],
    companions: dict[str, str],
    destination: str | None,
) -> None:
    blocked = {actor for actor, target in companions.items() if target == destination}
    if not blocked:
        return
    actors = TargetIndex([{"id": row.id, "name": row.name} for row in entities])
    intent.moved_entities = [
        move
        for move in intent.moved_entities or []
        if actors.resolve(move.entity_id) not in blocked
    ]
    manager._group_movement_resolution = (
        "GROUP MOVEMENT RESOLUTION: The proposed shared departure was not confirmed. "
        "The player and accompanying NPCs remain in the current scene. Do not narrate "
        "them as having arrived elsewhere or invent an obstacle. If the destination "
        "was unclear, clarify it naturally within the roleplay."
    )
