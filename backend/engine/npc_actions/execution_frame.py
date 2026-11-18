"""One turn-local public projection of existing owners after command publication.

The frame is derived data, not another state store. Consumers query the same
current owners again before model dispatch; cached ORM rows carry no authority.
"""

import json
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from backend.engine import turn_controls
from backend.engine.chpm import observable_state
from backend.engine.chpm.errors import StaleControlError
from backend.engine.clothing.context import actor_records
from backend.engine.clothing.projection import item_wear_state
from backend.engine.clothing.visuals import session_objects
from backend.engine.npc_actions import outcome_projection
from backend.engine.npc_actions.control import model_outcomes
from backend.engine.turn_replay.transactions import release_for_model
from backend.engine.visual_novel.continuity import PLAYER, SCENE, possession_snapshot

BACKGROUND_CONDITION_CHARS = 2048


@dataclass(frozen=True)
class Frame:
    binding: dict
    scene_id: str
    minute: int
    entities: dict[str, dict]
    observation: Any


def _actor(identifier: str) -> str:
    return "@player" if identifier == PLAYER else identifier


def _public_items(turn: Any, observation: Any) -> set[str]:
    """Use visibility evidence from this captured input, never the command's own choice."""
    result: set[str] = set()
    expected = (
        observation.session_id,
        observation.message_id,
        observation.revision_id,
        observation.content_hash,
        observation.scene_id,
    )
    for draft in getattr(turn, "action_drafts", {}).values():
        scope = getattr(draft, "scope", None)
        if (
            scope is None
            or (
                scope.session_id,
                scope.input_id,
                scope.input_revision,
                scope.input_hash,
                scope.scene_id,
            )
            != expected
        ):
            continue
        if all(
            scope.control.get(key) == turn.control.get(key)
            for key in ("attempt_id", "input_id", "input_revision", "input_hash")
        ):
            result.update(scope.public_item_ids)
    return result


def _known_items(outcomes: dict[str, list[dict]], public: set[str]) -> set[str]:
    return public & {
        effect["item_id"]
        for records in outcomes.values()
        for record in records
        if record.get("status") in {"applied", "attempted"}
        and isinstance(effect := record.get("effect"), dict)
        and isinstance(effect.get("item_id"), str)
    }


def _known_possessions(manager: Any, rows: list[Any], entities: dict, known: set[str]) -> None:
    """Previously public objects retain current custody after ceasing to be visible."""
    snapshot = possession_snapshot(manager, rows)
    actors = actor_records(manager, rows)
    for identifier in sorted(known - entities.keys()):
        owner = snapshot.owners.get(identifier)
        if owner is None:
            continue
        actor = actors.get(owner, {})
        wear = (
            item_wear_state(
                actor.get("visual_profile"),
                actor.get("resolved_inventory"),
                identifier,
                equipment=actor.get("equipment"),
            )
            if actor
            else "carried"
        )
        entities[identifier] = {
            "id": identifier,
            "kind": "item",
            "owner_id": _actor(owner),
            "wear_status": "not_worn" if wear == "carried" else wear,
            "worn_by": _actor(owner) if wear == "worn" else None,
        }
        position = (
            snapshot.items.get(identifier, {}).get("spatial_position") if owner == SCENE else None
        )
        if position:
            entities[identifier]["spatial_position"] = position


def _condition(record: dict) -> dict:
    return {**record, **({"meaning": "condition_note"} if record["kind"] == "item_state" else {})}


def _project(manager: Any, rows: list[Any], observation: Any, turn: Any) -> dict:
    view = observable_state.project(manager, rows, PLAYER, observation, own_facts=False)
    entities = deepcopy(view.entities)
    _known_possessions(
        manager,
        rows,
        entities,
        _known_items(model_outcomes(turn), _public_items(turn, observation)),
    )
    for entity in entities.values():
        for garment in entity.get("visible_clothing") or []:
            # Absence of an adjustment is explicit, never inferred from a note.
            garment.setdefault("uncovered_regions", [])
        if "recorded_conditions" in entity:
            entity["recorded_conditions"] = [
                _condition(row) for row in entity["recorded_conditions"]
            ]
    return entities


def intention(actor: str, decision: Any, outcomes: dict) -> dict:
    selected: dict = decision.selected.model_dump()
    if actor in outcomes:
        return {"subjective_selected_intention_not_world_facts": selected}
    return selected


async def capture(manager: Any, turn: Any, observation: Any) -> None:
    """Capture only published command control; legacy and unsubmitted plans are unchanged."""
    outcomes = model_outcomes(turn)
    if not outcomes:
        return
    if not turn_controls.bind_current(manager, turn.control, observation=observation):
        raise StaleControlError("The execution frame belongs to an inactive turn attempt.")
    before = turn_controls.scope(manager, "narration_review", observation=observation)
    rows = await session_objects(manager.db, manager.game_id, refresh=True)
    entities = _project(manager, rows, observation, turn)
    after = turn_controls.scope(manager, "narration_review", observation=observation)
    if before != after or not turn_controls.bind_current(manager, before, observation=observation):
        raise StaleControlError("The execution frame changed during owner projection.")
    turn.execution_frame = Frame(
        before,
        manager.state.current_scene_id,
        manager.state.in_game_time,
        entities,
        observation,
    )


def view(turn: Any) -> dict | None:
    frame = getattr(turn, "execution_frame", None)
    if not isinstance(frame, Frame):
        return None
    captured = turn_controls.binding(frame.binding)
    current = turn_controls.binding(turn.control)
    if (
        turn.input_id != captured.input_id
        or captured != current
        or frame.scene_id != frame.observation.scene_id
    ):
        raise StaleControlError("The execution frame does not match the current dialogue contract.")
    entities, omitted = _bounded_entities(frame.entities, _current_conditions(turn))
    return {
        "request_control": captured.model_dump(exclude_none=True, exclude={"phase"}),
        "scene_id": frame.scene_id,
        "minute": frame.minute,
        "entities": entities,
        **({"omitted_background_conditions": omitted} if omitted else {}),
        "recorded_conditions_are_exhaustive": False,
    }


def _ensure_binding(manager: Any, frame: Frame) -> None:
    if (
        frame.scene_id != manager.state.current_scene_id
        or frame.minute != manager.state.in_game_time
        or not turn_controls.bind_current(manager, frame.binding, observation=frame.observation)
    ):
        raise StaleControlError("The execution frame belongs to an inactive turn attempt.")


async def ensure_current(manager: Any, turn: Any) -> None:
    """Validate only this projection's owner dependencies, not unrelated private psychology."""
    frame = getattr(turn, "execution_frame", None)
    if not isinstance(frame, Frame):
        return
    view(turn)
    _ensure_binding(manager, frame)
    rows = await session_objects(manager.db, manager.game_id, refresh=True)
    _ensure_binding(manager, frame)
    entities = _project(manager, rows, frame.observation, turn)
    if entities != frame.entities:
        raise StaleControlError(
            "Current owner facts changed after the execution frame was captured."
        )
    # Keep these fresh owner reads out of the following inference interval.
    await release_for_model(manager)


def context(turn: Any) -> dict:
    frame = view(turn)
    return {"current_execution_frame": frame} if frame is not None else {}


def _current_conditions(turn: Any) -> set[str]:
    return {
        effect["condition_id"]
        for records in model_outcomes(turn).values()
        for record in records
        if record.get("status") == "applied"
        and isinstance(effect := record.get("effect"), dict)
        and isinstance(effect.get("condition_id"), str)
    }


def _bounded_conditions(entity: dict, required: set[str], remaining: int) -> tuple[dict, int, int]:
    if "recorded_conditions" not in entity:
        return entity, remaining, 0
    selected, omitted = [], 0
    for condition in entity["recorded_conditions"]:
        size = len(json.dumps(condition, ensure_ascii=False, separators=(",", ":")))
        if condition["id"] in required:
            selected.append(condition)
        elif size <= remaining:
            selected.append(condition)
            remaining -= size
        else:
            omitted += 1
    return (
        {
            **entity,
            "recorded_conditions": selected,
            **({"omitted_recorded_conditions": omitted} if omitted else {}),
        },
        remaining,
        omitted,
    )


def _bounded_entities(entities: dict, required: set[str]) -> tuple[dict, int]:
    result, remaining, omitted = {}, BACKGROUND_CONDITION_CHARS, 0
    for identifier, entity in deepcopy(entities).items():
        result[identifier], remaining, count = _bounded_conditions(entity, required, remaining)
        omitted += count
    return result, omitted


def records(turn: Any, outcomes: list[dict]) -> list[dict]:
    """Project public details and share input metadata; canonical receipts stay intact."""
    frame = getattr(turn, "execution_frame", None)
    if not isinstance(frame, Frame):
        return [outcome_projection.project(record, None) for record in outcomes]
    shared = {"attempt_id", "input_id", "input_revision", "input_hash"}
    if any(record.get(key) != frame.binding.get(key) for record in outcomes for key in shared):
        raise StaleControlError("An operation does not match the shared execution frame binding.")
    return [
        {
            **{key: value for key, value in record.items() if key not in shared},
            "request_control_ref": "/current_execution_frame/request_control",
        }
        for record in (outcome_projection.project(row, frame.entities) for row in outcomes)
    ]
