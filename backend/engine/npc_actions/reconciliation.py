"""Keep narrated extraction from repeating or reversing already owned command effects."""

from typing import Any

from backend.engine.narrated_items import independent_state
from backend.engine.narrated_items.schema import ItemExtraction
from backend.engine.physical_conditions.ledger import read

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
    if turn.initial.settings.mode != "live" or not turn.initial.settings.action_tools:
        return None
    actors = set(turn.action_outcomes) if turn.simplified else set(turn.decisions)
    return (
        {"controlled_actor_ids": sorted(actors), "outcomes": turn.action_outcomes}
        if actors
        else None
    )


def _effects(control: dict) -> list[dict]:
    return [
        {"actor_id": actor, **row["effect"]}
        for actor, rows in control["outcomes"].items()
        for row in rows
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
        and not _echo(action, effects)
    ]
    movements = [
        row
        for row in extraction.movements
        if not isinstance(row, dict) or row.get("actor_id") not in controlled
    ]
    errors.extend(
        "A narrated movement outside the approved NPC plan was preserved for review."
        for row in extraction.movements
        if isinstance(row, dict)
        and row.get("actor_id") in controlled
        and not any(
            effect.get("destination_scene_id") == row.get("destination_scene_id")
            and effect["actor_id"] == row.get("actor_id")
            for effect in effects
        )
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
    manager: Any, result: Any, actors: dict, *, original_actions: list[Any] | None = None
) -> tuple:
    extraction, failures, denied, indices = independent_state.unpack(
        result, actors, original_actions=original_actions
    )
    guarded, indices, errors = protect(manager, extraction, indices)
    return guarded, failures, denied, indices, errors


def _echo(action: Any, effects: list[dict]) -> bool:
    return any(
        effect.get("item_id") == action.item_id
        and (
            effect.get("source_owner") == action.source_owner
            and effect.get("destination_owner") == action.destination_owner
            or _wardrobe_echo(action, effect)
        )
        for effect in effects
    )


def _wardrobe_echo(action: Any, effect: dict) -> bool:
    if (
        action.source_owner != effect["actor_id"]
        or action.destination_owner != effect["actor_id"]
        or action.attachment_slot is not None
    ):
        return False
    if effect.get("operation") == "remove":
        return action.disposition in {"carried", "held"}
    return (
        effect.get("operation") in {"wear", "adjust"}
        and action.disposition == "worn"
        and (
            action.uncovered_regions is None
            or action.uncovered_regions == effect.get("uncovered_regions")
        )
    )


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
    for raw in updates:
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
            retained.append(raw)
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
