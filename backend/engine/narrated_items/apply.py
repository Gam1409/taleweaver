"""Copy-on-write item reconciliation; model output never supplies gameplay properties."""

from collections.abc import Sequence
from copy import deepcopy
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from backend.core.text_evidence import require_span
from backend.engine.clothing.classification import classify_action
from backend.engine.clothing.equipment_view import display_slots
from backend.engine.clothing.profiles import (
    load_profile,
    owned_items,
    validate_profile,
)
from backend.engine.clothing.schema import VisualProfile, WornItem
from backend.engine.item_logic import normalize_equipment_keys
from backend.engine.narrated_items import transitions
from backend.engine.narrated_items.errors import ItemFailure, ItemPolicyError
from backend.engine.narrated_items.participants import resolve_participants
from backend.engine.narrated_items.schema import ItemAction, ItemExtraction
from backend.engine.narrated_items.wear import placement, unchanged_observation, validate_wear
from backend.engine.visual_novel.continuity import PLAYER, SCENE, Possessions


def _id(item: Any) -> Any:
    return item.get("id") if isinstance(item, dict) else item


def _new_item(
    action: ItemAction,
    actors: dict,
    *,
    detailed: bool,
    session_id: str,
    message_id: str,
    index: int,
) -> dict:
    proposal = action.new_item
    if proposal is None:
        raise ValueError("Missing item identity.")
    owner = action.destination_owner if action.source_owner == SCENE else action.source_owner
    age = actors[owner].get("age_years")
    if (
        proposal.clothing
        and proposal.clothing.underwear
        and not (detailed and type(age) is int and age >= 18)
    ):
        raise ItemPolicyError("inner_creation_policy")
    origin = {"kind": "runtime", "session_id": session_id, "source_message_id": message_id}
    item: dict[str, Any] = {
        "id": "item_" + uuid5(NAMESPACE_URL, f"{session_id}:{message_id}:{index}").hex,
        "name": proposal.name,
        "description": proposal.description,
        "item_type": "WEARABLE" if proposal.clothing else "DEFAULT",
        "item_origin": origin,
    }
    if proposal.clothing:
        item.update(
            clothing=proposal.clothing.model_dump(),
            wearable_slots=proposal.wearable_slots,
            clothing_origin=origin,
        )
    return item


def _remove(actor: dict, item_id: str) -> None:
    actor["inventory"] = [item for item in actor["inventory"] if _id(item) != item_id]
    actor["resolved_inventory"] = [
        item for item in actor["resolved_inventory"] if _id(item) != item_id
    ]
    actor["equipment"] = {
        slot: None if _id(item) == item_id else item for slot, item in actor["equipment"].items()
    }
    raw = actor.get("visual_profile")
    if raw and load_profile(raw) is None:
        raise ValueError("Invalid appearance profile; item transfer requires review.")
    if raw:
        actor["visual_profile"]["worn"] = [
            w for w in raw.get("worn", []) if w["item_id"] != item_id
        ]


def _equip_worn(actor: dict, item: dict, preferred_slot: str | None) -> None:
    supplied = item.get("wearable_slots") or []
    supplied = [supplied] if isinstance(supplied, str) else supplied
    slots = [slot for raw in supplied for slot in display_slots([raw], [])]
    preferred = display_slots(preferred_slot, [])
    if preferred and preferred[0] in slots:
        slots.insert(0, preferred[0])
    equipment = normalize_equipment_keys(actor["equipment"])
    slot = next((slot for slot in slots if not equipment.get(slot)), None)
    if slot is None:
        return
    actor["equipment"][slot] = deepcopy(item)
    # Player equipment owns its item, matching slash equip/unequip semantics.
    actor["inventory"] = [row for row in actor["inventory"] if _id(row) != item["id"]]


def _receive(
    actor: dict,
    item: dict,
    disposition: str,
    detailed: bool,
    worn: WornItem | None = None,
    preferred_slot: str | None = None,
) -> None:
    identifier = item["id"]
    owned = owned_items(actor["inventory"], equipment=actor["equipment"])
    if identifier not in owned or not any(_id(row) == identifier for row in actor["inventory"]):
        actor["inventory"].append(deepcopy(item))
    actor["resolved_inventory"] = [
        row for row in actor["resolved_inventory"] if _id(row) != identifier
    ] + [deepcopy(item)]
    if disposition != "worn":
        return
    raw = actor.get("visual_profile")
    profile = load_profile(raw)
    if profile is None and not raw:
        profile = VisualProfile()
        profile.appearance.age_years = actor.get("age_years")
    if profile is None or worn is None:
        raise ValueError(
            "Wearing requires valid garment metadata and an existing appearance profile."
        )
    validate_wear(actor, item, profile, worn, detailed)
    if identifier not in {entry.item_id for entry in profile.worn}:
        profile.worn.append(worn)
    actor["visual_profile"] = validate_profile(
        profile.model_dump(), actor["resolved_inventory"], equipment=actor["equipment"]
    ).model_dump()
    # Clothing layers coexist in worn; receiving an item never equips it as a weapon.
    if actor["id"] == PLAYER and worn.attachment_slot is None:
        _equip_worn(actor, item, preferred_slot)


def _resolve(
    action: ItemAction, actors: dict, snapshot: Possessions, narration: str, **creation_options: Any
) -> dict:
    if action.basis not in {"completed", "observed_wear"}:
        raise ValueError(
            f"Action basis '{action.basis}' is not a completed action or current wear observation."
        )
    require_span(narration, action.evidence, action.evidence_span)
    if action.evidence not in narration:
        raise ValueError(
            "Item quote is not an exact contiguous substring of the completed narration."
        )
    if action.basis == "observed_wear" and (
        action.source_owner != action.destination_owner or action.disposition != "worn"
    ):
        raise ValueError("A wear observation cannot transfer or remove an item.")
    if action.destination_owner not in actors or (
        action.source_owner != SCENE and action.source_owner not in actors
    ):
        raise ValueError("An item participant is not present.")
    if action.item_id:
        item = snapshot.items.get(action.item_id)
        if item is None or snapshot.owners.get(action.item_id) not in {
            action.source_owner,
            action.destination_owner,
        }:
            raise ValueError("Item ownership does not match the described action.")
        return deepcopy(item)
    if action.new_item and any(
        str(item.get("name", "")).casefold() == action.new_item.name.casefold()
        for item in [*snapshot.items.values(), *snapshot.catalog.values()]
    ):
        raise ValueError("An existing item must be referenced by ID, not created again.")
    return _new_item(action, actors, **creation_options)


def _apply_batch(
    extraction: ItemExtraction,
    actors: dict,
    snapshot: Possessions,
    narration: str,
    *,
    detailed: bool,
    session_id: str,
    message_id: str,
    failures: list[ItemFailure] | None = None,
    source_indices: Sequence[int] | None = None,
) -> tuple[dict, Possessions, list[dict], list[str]]:
    """Propose one item chain on copies; the caller commits only a complete chain."""
    actors = deepcopy(actors)
    snapshot = deepcopy(snapshot)
    accepted: list[dict] = []
    errors: list[str] = []
    if source_indices is not None and (
        len(source_indices) != len(extraction.actions)
        or len(set(source_indices)) != len(source_indices)
        or any(type(value) is not int or not 0 <= value <= 5 for value in source_indices)
    ):
        raise ValueError("Invalid item action source indices.")
    for position, proposal in enumerate(extraction.actions):
        index = source_indices[position] if source_indices is not None else position
        action: ItemAction = proposal
        try:
            action = classify_action(resolve_participants(proposal, actors))
            item = _resolve(
                action,
                actors,
                snapshot,
                narration,
                detailed=detailed,
                session_id=session_id,
                message_id=message_id,
                index=index,
            )
            identifier = item["id"]
            actual_owner = snapshot.owners.get(identifier, action.source_owner)
            if actual_owner == action.destination_owner and action.source_owner != actual_owner:
                continue  # Already applied by the mechanics pass; never duplicate or unequip it.
            if unchanged_observation(action, actors[action.destination_owner], identifier):
                continue
            worn = placement(
                action,
                actors[action.destination_owner],
                identifier,
                same_owner=actual_owner == action.destination_owner,
                narration=narration,
                request_id=message_id,
            )
            candidate = deepcopy(actors)
            preferred_slot = next(
                (
                    slot
                    for slot, value in candidate[action.destination_owner]["equipment"].items()
                    if _id(value) == identifier
                ),
                None,
            )
            if actual_owner in candidate:
                _remove(candidate[actual_owner], identifier)
            _receive(
                candidate[action.destination_owner],
                item,
                action.disposition,
                detailed,
                worn,
                preferred_slot,
            )
            actors = candidate
            snapshot.items[identifier] = item
            snapshot.owners[identifier] = action.destination_owner
            accepted.append(
                {
                    "action_index": index,
                    "item": item,
                    "source_owner": actual_owner,
                    "destination_owner": action.destination_owner,
                    "disposition": action.disposition,
                    "evidence": action.evidence,
                    **(
                        {"evidence_span": action.evidence_span.model_dump()}
                        if action.evidence_span
                        else {}
                    ),
                }
            )
        except ValueError as exc:
            label = action.new_item.name if action.new_item else action.item_id
            failure = ItemFailure(
                str(label),
                str(exc),
                exc.code if isinstance(exc, ItemPolicyError) else None,
                basis=action.basis,
                evidence=action.evidence,
                action_index=index,
            )
            errors.append(failure.message())
            if failures is not None:
                failures.append(failure)
    return actors, snapshot, accepted, errors


def _prepare_actions(
    batches: list[list[tuple[int, ItemAction]]],
    actors: dict,
    snapshot: Possessions,
    narration: str,
) -> tuple[list[tuple[int, ItemAction]], list[ItemFailure]]:
    eligible: list[tuple[int, ItemAction]] = []
    failures: list[ItemFailure] = []
    for entries in batches:
        try:
            actions = transitions.prepare(entries, actors, narration)
            if not transitions.already_applied(actions, snapshot):
                eligible.extend(
                    (index, action) for (index, _), action in zip(entries, actions, strict=True)
                )
        except ValueError as exc:
            index, action = entries[0]
            failures.append(
                ItemFailure(
                    action.item_id or (action.new_item.name if action.new_item else "Item"),
                    str(exc),
                    basis=action.basis,
                    evidence=action.evidence,
                    action_index=index,
                )
            )
    return sorted(eligible, key=lambda entry: entry[0]), failures


def _commit_chains(
    eligible: list[tuple[int, ItemAction]],
    actors: dict,
    snapshot: Possessions,
    narration: str,
    *,
    detailed: bool,
    session_id: str,
    message_id: str,
) -> tuple[dict, list[dict], list[ItemFailure]]:
    failures: list[ItemFailure] = []
    # At most six local passes: each rejected pass excludes at least one item chain.
    # Nothing is persisted until a complete pass succeeds, in original action order.
    while eligible:
        rejected: list[ItemFailure] = []
        changed, _, accepted, _ = _apply_batch(
            ItemExtraction.model_validate(
                {"actions": [action.model_dump() for _, action in eligible]}
            ),
            actors,
            snapshot,
            narration,
            detailed=detailed,
            session_id=session_id,
            message_id=message_id,
            failures=rejected,
            source_indices=[index for index, _ in eligible],
        )
        if not rejected:
            return changed, accepted, failures
        failures.extend(rejected)
        invalid_indices = {failure.action_index for failure in rejected}
        invalid_items = {
            action.item_id
            for index, action in eligible
            if index in invalid_indices and action.item_id is not None
        }
        eligible = [
            (index, action)
            for index, action in eligible
            if index not in invalid_indices and action.item_id not in invalid_items
        ]
    return actors, [], failures


def apply_actions(
    extraction: ItemExtraction,
    actors: dict,
    snapshot: Possessions,
    narration: str,
    *,
    detailed: bool,
    session_id: str,
    message_id: str,
    failures: list[ItemFailure] | None = None,
    source_indices: Sequence[int] | None = None,
) -> tuple[dict, list[dict], list[str]]:
    """Commit item chains atomically without reordering interleaved independent actions."""
    batches = transitions.batches(extraction.actions, source_indices)
    eligible, rejected = _prepare_actions(batches, actors, snapshot, narration)
    changed, accepted, failed = _commit_chains(
        eligible,
        actors,
        snapshot,
        narration,
        detailed=detailed,
        session_id=session_id,
        message_id=message_id,
    )
    rejected.extend(failed)
    if failures is not None:
        failures.extend(rejected)
    return changed, accepted, [failure.message() for failure in rejected]
