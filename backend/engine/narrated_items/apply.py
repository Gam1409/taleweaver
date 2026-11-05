"""Copy-on-write item reconciliation; model output never supplies gameplay properties."""

from copy import deepcopy
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from backend.engine.clothing.profiles import (
    garment_for_item,
    load_profile,
    owned_items,
    validate_profile,
)
from backend.engine.clothing.schema import VisualProfile, WornItem
from backend.engine.narrated_items.errors import ItemFailure, ItemPolicyError
from backend.engine.narrated_items.participants import resolve_participants
from backend.engine.narrated_items.schema import ItemAction, ItemExtraction
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


def _receive(actor: dict, item: dict, disposition: str, detailed: bool) -> None:
    identifier = item["id"]
    owned = owned_items(actor["inventory"], equipment=actor["equipment"])
    if identifier not in owned or not any(_id(row) == identifier for row in actor["inventory"]):
        actor["inventory"].append(deepcopy(item))
    actor["resolved_inventory"] = [
        row for row in actor["resolved_inventory"] if _id(row) != identifier
    ] + [deepcopy(item)]
    if disposition != "worn":
        return
    garment = garment_for_item(item)
    raw = actor.get("visual_profile")
    profile = load_profile(raw)
    if profile is None and not raw:
        profile = VisualProfile()
        profile.appearance.age_years = actor.get("age_years")
    if garment is None or profile is None:
        raise ValueError(
            "Wearing requires valid garment metadata and an existing appearance profile."
        )
    age = actor.get("age_years")
    if garment.underwear and not (detailed and type(age) is int and age >= 18):
        raise ItemPolicyError("inner_wear_policy")
    if identifier not in {entry.item_id for entry in profile.worn}:
        profile.worn.append(WornItem(item_id=identifier))
    actor["visual_profile"] = validate_profile(
        profile.model_dump(), actor["resolved_inventory"], equipment=actor["equipment"]
    ).model_dump()
    # Clothing layers coexist in worn; receiving an item never equips it as a weapon.
    for slot in item.get("wearable_slots") or []:
        if actor["id"] == PLAYER and not actor["equipment"].get(slot):
            actor["equipment"][slot] = deepcopy(item)


def _resolve(
    action: ItemAction, actors: dict, snapshot: Possessions, narration: str, **creation_options: Any
) -> dict:
    if action.basis not in {"completed", "observed_wear"} or action.evidence not in narration:
        raise ValueError("No exact evidence of a completed item action.")
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
) -> tuple[dict, list[dict], list[str]]:
    """Validate each action on copies; failures never partially remove possessions."""
    actors = deepcopy(actors)
    snapshot = deepcopy(snapshot)
    accepted: list[dict] = []
    errors: list[str] = []
    seen: set[str] = set()
    for index, proposal in enumerate(extraction.actions):
        action = proposal
        try:
            action = resolve_participants(proposal, actors)
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
            if identifier in seen:
                raise ValueError("Multiple actions for the same item need review.")
            seen.add(identifier)
            actual_owner = snapshot.owners.get(identifier, action.source_owner)
            if actual_owner == action.destination_owner and action.source_owner != actual_owner:
                continue  # Already applied by the mechanics pass; never duplicate or unequip it.
            profile = load_profile(actors[action.destination_owner].get("visual_profile"))
            if (
                action.basis == "observed_wear"
                and profile
                and any(row.item_id == identifier for row in profile.worn)
            ):
                continue
            candidate = deepcopy(actors)
            if actual_owner in candidate:
                _remove(candidate[actual_owner], identifier)
            _receive(candidate[action.destination_owner], item, action.disposition, detailed)
            actors = candidate
            snapshot.items[identifier] = item
            snapshot.owners[identifier] = action.destination_owner
            accepted.append(
                {
                    "item": item,
                    "source_owner": actual_owner,
                    "destination_owner": action.destination_owner,
                    "disposition": action.disposition,
                    "evidence": action.evidence,
                }
            )
        except ValueError as exc:
            label = action.new_item.name if action.new_item else action.item_id
            failure = ItemFailure(
                str(label), str(exc), exc.code if isinstance(exc, ItemPolicyError) else None
            )
            errors.append(failure.message())
            if failures is not None:
                failures.append(failure)
    return actors, accepted, errors
