"""Keep narrated extraction from repeating or reversing already owned command effects."""

from typing import Any

from pydantic import ValidationError

from backend.engine import turn_controls
from backend.engine.narrated_items import independent_state
from backend.engine.narrated_items.participants import resolve_participants
from backend.engine.narrated_items.schema import ItemExtraction
from backend.engine.narrated_movement.runtime import exclude_commands
from backend.engine.narrated_movement.schema import MovementProposal
from backend.engine.npc_actions import custody_check, custody_effects, narration_fence
from backend.engine.npc_actions.control import validated_outcomes
from backend.engine.physical_conditions.ledger import read
from backend.engine.physical_conditions.schema import ConditionProposal, Ledger
from backend.engine.physical_conditions.update_identity import normalize

INSTRUCTIONS = """
When npc_command_control is supplied, inventory, wardrobe and room travel for
controlled_actor_ids are owned by their command API. Its outcomes have already
been applied where status is applied. Do not repeat those effects in actions or
movements, and do not invent new ownership/wear/travel changes for these actors.
Mark passages describing only already-applied effects unchanged. Keep independent
injuries, body conditions, environment changes, and other actors' supported effects.
Protected item dimensions already have their current canonical value; do not
record/change/resolve them again. Other dimensions on the same item remain eligible.
"""


def context(manager: Any) -> dict | None:
    turn = getattr(manager, "_chpm_turn", None)
    if turn is None or turn.input_id != getattr(manager, "_vn_player_message_id", None):
        return None
    if not turn_controls.bind_current(manager, getattr(turn, "control", {})):
        return None
    if turn.initial.settings.mode != "live" or not turn.initial.settings.action_tools:
        return None
    actors = set(turn.action_outcomes) if turn.simplified else set(turn.decisions)
    return (
        {"controlled_actor_ids": sorted(actors), "outcomes": validated_outcomes(turn)}
        if actors
        else None
    )


def _effects(control: dict) -> list[dict]:
    rows = [(actor, row) for actor, records in control["outcomes"].items() for row in records]
    return [
        {**row["effect"], "actor_id": actor, "_publication_index": position}
        for position, (actor, row) in enumerate(rows)
        if row.get("status") == "applied" and isinstance(row.get("effect"), dict)
    ]


def protect(
    manager: Any, extraction: ItemExtraction, indices: tuple[int, ...] | None = None
) -> tuple[ItemExtraction, tuple[int, ...] | None, list[str]]:
    control = context(manager)
    if not control:
        return extraction, indices, []
    controlled = set(control["controlled_actor_ids"])
    effects = _effects(control)
    pairs = zip(
        extraction.actions,
        indices if indices is not None else range(len(extraction.actions)),
        strict=True,
    )
    kept = [
        (action, index)
        for action, index in pairs
        if action.source_owner not in controlled and action.destination_owner not in controlled
    ]
    errors = [
        "A narrated inventory change outside the approved NPC plan was preserved for review."
        for action in extraction.actions
        if (action.source_owner in controlled or action.destination_owner in controlled)
        and not custody_effects.echo(action, effects)
    ]
    movement_pairs = [(raw, _movement(raw)) for raw in extraction.movements]
    movements = [raw for raw, row in movement_pairs if row.get("actor_id") not in controlled]
    errors.extend(
        "A narrated movement outside the approved NPC plan was preserved for review."
        for _, row in movement_pairs
        if row.get("actor_id") in controlled and not _movement_echo(row, effects)
    )
    conditions, condition_errors = _conditions(manager, extraction.condition_updates, effects)
    return (
        extraction.model_copy(
            update={
                "actions": [action for action, _ in kept],
                "movements": movements,
                "condition_updates": conditions,
            }
        ),
        tuple(index for _, index in kept),
        [*errors, *condition_errors],
    )


def unpack(
    manager: Any,
    result: Any,
    actors: dict,
    *,
    original_actions: list[Any] | None = None,
    narration: str = "",
    resolution: str = "",
    retry: custody_check.Recheck | None = None,
    actions_provided: bool = True,
) -> tuple:
    extraction, failures, denied, indices = independent_state.unpack(
        result, actors, original_actions=original_actions
    )
    control = context(manager)
    if retry is not None and (not control or failures or not actions_provided):
        raise custody_check.CustodyDisagreementError(retry)
    if control:
        extraction = extraction.model_copy(
            update={"actions": [_participants(action, actors) for action in extraction.actions]}
        )
        custody_check.compare(manager._chpm_turn, narration, resolution, extraction.actions, retry)
    narration_fence.items(manager, extraction.actions)
    guarded, indices, errors = protect(manager, extraction, indices)
    if control:
        effects = _effects(control)
        excluded = [
            row
            for raw in extraction.movements
            if (row := _movement(raw)).get("actor_id") in control["controlled_actor_ids"]
            and not _movement_echo(row, effects)
        ]
        exclude_commands(
            manager,
            excluded,
            original_count=len(extraction.movements),
            control=manager._chpm_turn.control,
        )
    return guarded, failures, denied, indices, errors


def _participants(action: Any, actors: dict) -> Any:
    try:
        return resolve_participants(action, actors)
    except ValueError:
        return action


def _movement(raw: Any) -> dict:
    try:
        return MovementProposal.model_validate(raw).model_dump()
    except ValidationError:
        return {}


def _movement_echo(row: dict, effects: list[dict]) -> bool:
    return any(
        effect["actor_id"] == row.get("actor_id")
        and (
            isinstance(effect.get("destination_scene_id"), str)
            and effect["destination_scene_id"] == row.get("destination_scene_id")
            and row.get("presence") == "present"
            or "presence" in effect
            and row.get("destination_scene_id") is None
            and effect["presence"] == row.get("presence")
        )
        for effect in effects
    )


def _condition(raw: Any, ledger: Ledger) -> Any:
    candidate, _ = normalize(raw, ledger, {row.target_id for row in ledger.conditions.values()})
    try:
        return ConditionProposal.model_validate(candidate).model_dump()
    except ValidationError:
        return raw


def _conditions(manager: Any, updates: list, effects: list[dict]) -> tuple[list, list[str]]:
    protected = {
        (effect["item_id"], effect["dimension"].casefold())
        for effect in effects
        if "item_id" in effect and isinstance(effect.get("dimension"), str)
    }
    if not protected:
        return updates, []
    ledger = read(manager.state.entity_states)
    current = {
        (row.target_id, row.part.casefold()): row
        for row in ledger.conditions.values()
        if row.kind == "item_state" and row.status != "resolved"
    }
    retained, errors = [], []
    for original in updates:
        raw = _condition(original, ledger)
        key = raw.get("condition_id") if isinstance(raw, dict) else None
        known = ledger.conditions.get(key) if isinstance(key, str) else None
        identity = (
            (known.target_id, known.part.casefold())
            if known
            else (raw.get("target_id"), str(raw.get("part", "")).casefold())
            if isinstance(raw, dict)
            and raw.get("kind") == "item_state"
            and isinstance(raw.get("target_id"), str)
            and isinstance(raw.get("part"), str)
            else None
        )
        if identity not in protected:
            retained.append(original)
            continue
        fact = current.get(identity)
        if (
            not fact
            or raw.get("operation") not in {"record", "change"}
            or raw.get("detail") != fact.detail
            or raw.get("visibility") not in {None, fact.visibility}
        ):
            errors.append(
                "A narrated change to a command-owned item dimension was preserved for review."
            )
    return retained, errors
