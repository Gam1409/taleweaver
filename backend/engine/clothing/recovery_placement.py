"""Restore evidenced placement of a registered garment without recreating it."""

from copy import deepcopy
from hashlib import sha256

from backend.engine.clothing.profiles import load_profile, validate_profile
from backend.engine.clothing.recovery_schema import RecoveryEntry
from backend.engine.clothing.resolution_facts import inner_details_allowed
from backend.engine.clothing.schema import Garment, WornItem
from backend.engine.narrated_items.errors import ItemFailure, ItemPolicyError
from backend.engine.visual_novel.continuity import Possessions


def restore(
    actors: dict,
    entry: RecoveryEntry,
    garment: Garment,
    snapshot: Possessions,
    detailed: bool,
    *,
    source: dict,
) -> tuple[dict, list[dict], list[ItemFailure]]:
    """Caller already verified ownership and literal source/placement quotations."""
    action = entry.action
    actor = actors[action.source_owner]
    profile = load_profile(actor.get("visual_profile"))
    worn = (
        next((row for row in profile.worn if row.item_id == action.item_id), None)
        if profile
        else None
    )
    if (
        not entry.placement_evidence
        or not (entry.uncovered_regions or entry.restore_coverage)
        or action.disposition != "worn"
        or worn is None
        or (
            worn.uncovered_regions == entry.uncovered_regions
            and (not entry.uncovered_regions or _same_source(worn, entry, source))
        )
    ):
        return actors, [], []
    try:
        if garment.underwear and not inner_details_allowed(actor.get("visual_profile"), detailed):
            raise ItemPolicyError("inner_wear_policy")
        candidate = deepcopy(actor)
        profile = load_profile(candidate["visual_profile"])
        if profile is None:
            raise ValueError("The appearance profile is unavailable.")
        profile.worn = [
            row.model_copy(update={"uncovered_regions": list(entry.uncovered_regions)})
            if row.item_id == action.item_id
            else row
            for row in profile.worn
        ]
        candidate["visual_profile"] = validate_profile(
            profile, candidate["resolved_inventory"], equipment=candidate["equipment"]
        ).model_dump()
    except ValueError as exc:
        return (
            actors,
            [],
            [
                ItemFailure(
                    str(action.item_id),
                    str(exc),
                    exc.code if isinstance(exc, ItemPolicyError) else None,
                    basis=action.basis,
                    evidence=action.evidence,
                )
            ],
        )
    item = deepcopy(snapshot.items[action.item_id or ""])
    addition = {
        "action_index": 0,
        "item": item,
        "source_owner": action.source_owner,
        "destination_owner": action.destination_owner,
        "disposition": action.disposition,
        "evidence": action.evidence,
    }
    return {**actors, action.source_owner: candidate}, [addition], []


def _same_source(worn: WornItem, entry: RecoveryEntry, source: dict) -> bool:
    proof = worn.source
    return bool(
        proof is not None
        and proof.source_message_id == entry.source_message_id
        and proof.content_hash == sha256(source["content"].encode()).hexdigest()
        and proof.evidence == entry.placement_evidence
        and proof.source_role == source["role"]
        and (
            proof.evidence_span is None
            or proof.evidence_span.matches(source["content"], proof.evidence)
        )
    )
