"""Keep unrelated state sections without allowing rejected item effects to re-enter."""

from typing import Any

from pydantic import ValidationError

from backend.engine.narrated_items.errors import ItemFailure
from backend.engine.narrated_items.schema import ItemExtraction, SharedItemExtraction
from backend.engine.physical_conditions.ledger import read as read_conditions
from backend.engine.scene_continuity.ledger import read as read_scene

INSTRUCTIONS = """
When item_changes_allowed is false, return no item actions. Independent physical
and scene updates are allowed only when independent_state_scope is supplied.
Use only current supplied targets outside blocked_subject_ids; never record the rejected action's consequences through
another section or a room-level proxy. Clothing, ownership and presence remain
canonical. Unknown dependencies require review, not inferred success.
"""


def action_scope(actions: list[Any], actors: dict) -> set[str]:
    denied: set[str] = set()
    for proposal in actions:
        raw = proposal.model_dump() if hasattr(proposal, "model_dump") else proposal
        if not isinstance(raw, dict):
            denied.update(actors)
            continue
        if isinstance(raw.get("item_id"), str):
            denied.add(raw["item_id"])
        for field in ("source_owner", "destination_owner"):
            owner = raw.get(field)
            denied.update({owner} if isinstance(owner, str) and owner in actors else actors)
    return denied


def unpack(
    result: Any, actors: dict
) -> tuple[ItemExtraction, list[ItemFailure], set[str] | None, tuple[int, ...] | None]:
    if not isinstance(result, SharedItemExtraction):
        return ItemExtraction.model_validate(result), [], None, None
    body = result.model_dump(exclude={"staging"})
    extraction = ItemExtraction.model_validate({**body, "actions": []})
    if len(result.actions) > 6:
        failure = ItemFailure(
            "Item proposals",
            "The action batch exceeds six proposals; no item changes were applied.",
        )
        return extraction, [failure], action_scope(result.actions, actors), ()
    valid, indices, failures, denied = [], [], [], set()
    invalid_items: set[str] = set()
    for index, raw in enumerate(result.actions):
        try:
            value = ItemExtraction(actions=[raw]).actions[0]
        except ValidationError:
            failures.append(
                ItemFailure(
                    f"Item proposal {index + 1}",
                    "The item action failed schema validation.",
                    action_index=index,
                )
            )
            denied.update(action_scope([raw], actors))
            if isinstance(raw, dict) and isinstance(raw.get("item_id"), str):
                invalid_items.add(raw["item_id"])
            continue
        valid.append(value)
        indices.append(index)
    retained = [
        (value, index)
        for value, index in zip(valid, indices, strict=True)
        if value.item_id not in invalid_items
    ]
    return (
        extraction.model_copy(update={"actions": [value for value, _ in retained]}),
        failures,
        denied or None,
        tuple(index for _, index in retained),
    )


def select(
    manager: Any, extraction: ItemExtraction, denied: set[str], condition_targets: set[str]
) -> tuple[ItemExtraction, int]:
    pending = getattr(manager, "_pending_scene_continuity", None)
    try:
        conditions = read_conditions(manager.state.entity_states).conditions
        scene = read_scene(manager.state.entity_states).records
    except ValueError:
        conditions, scene = {}, {}
    updates = [
        row
        for row in extraction.condition_updates
        if _allowed(row, "target_id", "condition_id", conditions, condition_targets, denied)
    ]
    scene_updates = [
        row
        for row in extraction.scene_updates
        if _allowed(
            row,
            "subject_id",
            "record_id",
            scene,
            (pending.targets - {manager.state.current_scene_id}) if pending else set(),
            denied,
        )
    ]
    actions = [
        row
        for row in extraction.final_frame_actions
        if _frame_allowed(row, pending.actor_targets if pending else set(), denied)
    ]
    rejected = (
        len(extraction.condition_updates)
        + len(extraction.scene_updates)
        + len(extraction.final_frame_actions)
        - len(updates)
        - len(scene_updates)
        - len(actions)
    )
    return extraction.model_copy(
        update={
            "condition_updates": updates,
            "scene_updates": scene_updates,
            "final_frame_actions": actions,
        }
    ), rejected


def _allowed(
    raw: Any, field: str, reference: str, known: dict, targets: set[str], denied: set[str]
) -> bool:
    if not isinstance(raw, dict):
        return False
    key = raw.get(reference)
    row = known.get(key) if isinstance(key, str) else None
    target = raw.get(field) or getattr(row, field, None)
    return isinstance(target, str) and target in targets and target not in denied


def _frame_allowed(raw: Any, targets: set[str], denied: set[str]) -> bool:
    actors = raw.get("actor_ids") if isinstance(raw, dict) else None
    return (
        isinstance(actors, list)
        and bool(actors)
        and all(isinstance(key, str) and key in targets and key not in denied for key in actors)
    )
