"""Resolve one canonical item's final worn placement before mutating its owner."""

from hashlib import sha256

from backend.engine.clothing.body_schema import WearSource
from backend.engine.clothing.profiles import attachment_item_allowed, garment_for_item, load_profile
from backend.engine.clothing.schema import VisualProfile, WornItem
from backend.engine.narrated_items.errors import ItemPolicyError
from backend.engine.narrated_items.schema import ItemAction


def unchanged_observation(action: ItemAction, actor: dict, identifier: str) -> bool:
    profile = load_profile(actor.get("visual_profile"))
    if action.basis != "observed_wear" or profile is None:
        return False
    for row in profile.worn:
        same = (
            row.item_id == identifier
            and (
                action.uncovered_regions is None
                or row.uncovered_regions == action.uncovered_regions
            )
            and (action.attachment_slot is None or row.attachment_slot == action.attachment_slot)
        )
        needs_source = row.source is None and bool(
            action.uncovered_regions or action.attachment_slot
        )
        if same and not needs_source:
            return True
    return False


def placement(
    action: ItemAction,
    actor: dict,
    identifier: str,
    *,
    same_owner: bool,
    narration: str,
    request_id: str,
) -> WornItem | None:
    if action.disposition != "worn":
        return None
    profile = load_profile(actor.get("visual_profile"))
    old = (
        next((row for row in profile.worn if row.item_id == identifier), None)
        if profile and same_owner
        else None
    )
    slot = action.attachment_slot or (old.attachment_slot if old else None)
    if slot and action.uncovered_regions is not None:
        raise ValueError("Body placement cannot carry clothing displacement.")
    uncovered = action.uncovered_regions
    if uncovered is None:
        uncovered = old.uncovered_regions if old and not slot else []
    source = None
    if slot or uncovered:
        source = (
            old.source
            if old and action.uncovered_regions is None and action.attachment_slot is None
            else WearSource(
                request_id=request_id,
                content_hash=sha256(narration.encode()).hexdigest(),
                evidence=action.evidence,
                evidence_span=action.evidence_span,
            )
        )
    return WornItem(
        item_id=identifier,
        uncovered_regions=uncovered,
        attachment_slot=slot,
        source=source,
    )


def validate_wear(
    actor: dict, item: dict, profile: VisualProfile, worn: WornItem, detailed: bool
) -> None:
    garment = garment_for_item(item)
    age = actor.get("age_years")
    if worn.attachment_slot:
        if type(age) is not int or age < 18:
            raise ValueError("Body attachment requires an established adult character.")
        if not attachment_item_allowed(item):
            raise ValueError("An ordinary garment cannot become a body attachment.")
        allowed = profile.body.attachment_slots if profile.body else None
        if allowed is not None and worn.attachment_slot not in allowed:
            raise ValueError("This body region is not available on the character.")
        return
    if garment is None:
        raise ValueError("Wearing requires valid garment metadata.")
    if garment.underwear and not (detailed and type(age) is int and age >= 18):
        raise ItemPolicyError("inner_wear_policy")
