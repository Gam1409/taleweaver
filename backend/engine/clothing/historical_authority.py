"""Historical command-owned prose may describe current wear but never execute it."""

from typing import Any

from backend.engine.clothing.profiles import load_profile
from backend.engine.clothing.projection import item_wear_state


def controlled(plan: Any, change: Any, *, creation_index: int | None = None) -> bool:
    if plan.sources is None:
        return False
    actors = plan.sources.narration_control.actor_ids
    narrated_action = change.source == "completed_narration"
    if narrated_action and change.actor_id in actors:
        return True
    narrated_gift = narrated_action or creation_index in plan.narrated_gift_indices
    return bool(
        narrated_gift
        and getattr(change, "acquisition", None) == "gift"
        and change.source_id in actors
    )


def echo(actor: dict, action: Any) -> bool:
    """A zero-delta echo keeps the original owner's proof, including command proof."""
    placement = item_wear_state(
        actor["visual_profile"],
        actor["resolved_inventory"],
        action.item_id,
        equipment=actor["equipment"],
    )
    if action.operation == "remove":
        return placement == "carried"
    profile = load_profile(actor["visual_profile"])
    if placement != "worn" or profile is None:
        return False
    worn = next((row for row in profile.worn if row.item_id == action.item_id), None)
    return bool(
        worn is not None
        and worn.attachment_slot is None
        and set(worn.uncovered_regions) == set(action.uncovered_regions)
    )
