"""Apply validated VN wardrobe changes after canonical ownership transfers."""

import json
from copy import deepcopy
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import select

from backend.engine.clothing.actions import WardrobeAction
from backend.engine.clothing.context import actor_records, detail_settings, resolved_inventory
from backend.engine.clothing.profiles import (
    garment_for_item,
    load_profile,
    owned_items,
    reconcile_profile,
    validate_profile,
)
from backend.engine.clothing.schema import VisualProfile, WornItem
from backend.engine.visual_novel.continuity import PLAYER
from backend.models.world_entity import WorldEntity

LEDGER_KEY = "__vn_wardrobe__"


def _detail_allowed(actor: dict, manager: Any) -> bool:
    profile = load_profile(actor["visual_profile"])
    return bool(
        detail_settings(manager)["detailed"]
        and profile
        and profile.appearance.age_years is not None
        and profile.appearance.age_years >= 18
    )


def _store_actor(manager: Any, states: dict, actor: dict) -> None:
    if actor["id"] == PLAYER:
        manager.avatar.visual_profile = deepcopy(actor["visual_profile"])
        manager.avatar.inventory = deepcopy(actor["inventory"])
        manager.avatar.equipment = deepcopy(actor["equipment"])
    else:
        states[actor["id"]] = {
            **states.get(actor["id"], {}),
            "visual_profile": deepcopy(actor["visual_profile"]),
            "inventory": deepcopy(actor["inventory"]),
        }


def _profile(actor: dict) -> VisualProfile:
    current = actor["visual_profile"]
    profile = load_profile(current)
    if profile is None and current:
        raise ValueError("Unsupported visual profile was preserved.")
    return profile or VisualProfile()


def _change_wear(actor: dict, action: WardrobeAction) -> None:
    profile = _profile(actor)
    items = owned_items(actor["resolved_inventory"], equipment=actor["equipment"])
    if action.item_id not in items:
        raise ValueError("The character does not own that garment.")
    worn = {item.item_id: item for item in profile.worn}
    equipped = {
        value.get("id") if isinstance(value, dict) else value
        for value in actor["equipment"].values()
    }
    if action.operation != "wear" and action.item_id not in worn and action.item_id not in equipped:
        raise ValueError("That garment is not currently worn.")
    if action.operation == "remove":
        worn.pop(action.item_id, None)
    else:
        worn[action.item_id] = WornItem(
            item_id=action.item_id, uncovered_regions=action.uncovered_regions
        )
    profile.worn = list(worn.values())
    actor["visual_profile"] = validate_profile(
        profile, actor["resolved_inventory"], equipment=actor["equipment"]
    ).model_dump()
    if action.operation == "remove":
        carried = owned_items(actor["inventory"])
        if action.item_id not in carried:
            actor["inventory"].append(deepcopy(items[action.item_id]))
            actor["resolved_inventory"].append(deepcopy(items[action.item_id]))
        actor["equipment"] = {
            slot: None
            if (value.get("id") if isinstance(value, dict) else value) == action.item_id
            else value
            for slot, value in actor["equipment"].items()
        }


def _reconcile(manager: Any, entities: list[Any], states: dict) -> bool:
    changed = False
    avatar = manager.avatar
    raw = getattr(avatar, "visual_profile", None)
    profile = reconcile_profile(
        raw, resolved_inventory(avatar.inventory, entities, states), equipment=avatar.equipment
    )
    if profile is not None and profile != raw:
        avatar.visual_profile = profile
        changed = True
    for entity in entities:
        if entity.entity_type != "NPC":
            continue
        override = states.get(entity.id, {})
        raw = override.get("visual_profile", getattr(entity, "visual_profile", None))
        inventory = override.get(
            "inventory", entity.inventory or (entity.metadata_json or {}).get("inventory") or []
        )
        profile = reconcile_profile(raw, resolved_inventory(inventory, entities, states))
        if profile is not None and profile != raw:
            states[entity.id] = {**override, "visual_profile": profile}
            changed = True
    return changed


def _create_garment(
    manager: Any, event: Any, plan: Any, actors: dict, creation: Any, index: int
) -> tuple[dict, dict]:
    actor = actors.get(creation.actor_id)
    if plan.scene_id != manager.state.current_scene_id or actor is None:
        raise ValueError("The clothing source or character is no longer in the current location.")
    if creation.clothing.underwear and not _detail_allowed(actor, manager):
        raise ValueError(
            "Detailed garment tracking is unavailable for the current settings or known age."
        )
    if creation.acquisition == "gift" and creation.source_id not in actors:
        raise ValueError("The giver is no longer present.")
    if creation.acquisition == "craft" and not set(creation.material_item_ids).issubset(
        set(event.deleted_entities or [])
    ):
        raise ValueError("Crafting did not consume its required materials; no garment was created.")
    if any(
        item.get("name", "").casefold() == creation.name.casefold()
        for owner in actors.values()
        for item in owner["resolved_inventory"]
    ):
        raise ValueError("An existing garment must be transferred rather than duplicated.")
    identifier = (
        "garment_"
        + uuid5(NAMESPACE_URL, f"{manager.state.session_id}:{plan.message_id}:{index}").hex
    )
    candidate = deepcopy(actor)
    item = {
        "id": identifier,
        "name": creation.name,
        "description": creation.description,
        "item_type": "CLOTHING",
        "clothing": creation.clothing.model_dump(),
        "clothing_origin": {
            "kind": "runtime",
            "session_id": manager.state.session_id,
            "source_message_id": plan.message_id,
        },
    }
    candidate["inventory"].append(item)
    candidate["resolved_inventory"].append(deepcopy(item))
    if creation.wear:
        evidence_fields = {
            "actor_id",
            "source",
            "evidence",
            "basis",
            "agency",
            "reason",
            "npc_decision",
        }
        _change_wear(
            candidate,
            WardrobeAction(
                **creation.model_dump(include=evidence_fields), item_id=identifier, operation="wear"
            ),
        )
    completed = {
        "actor_id": creation.actor_id,
        "item_id": identifier,
        "name": creation.name,
        "acquisition": creation.acquisition,
        "source_id": creation.source_id,
        "worn": creation.wear,
    }
    return candidate, completed


async def apply_wardrobe(manager: Any, event: Any, states: dict) -> bool:
    """No arbitrary NPC inventory replacement; each acquisition appends one cosmetic item."""
    entities = list(
        (
            await manager.db.scalars(
                select(WorldEntity).where(WorldEntity.session_id == manager.state.session_id)
            )
        ).all()
    )
    changed = _reconcile(manager, entities, states)
    manager._vn_wardrobe_changed = changed
    plan = getattr(event, "_vn_clothing_plan", None)
    if plan is None:
        return changed
    ledger = states.get(LEDGER_KEY, {})
    processed = ledger.get("processed_message_ids", []) if isinstance(ledger, dict) else []
    if plan.message_id in processed:
        return changed
    actors = actor_records(manager, entities, states)
    errors = list(plan.errors)
    accepted = []
    same_scene = plan.scene_id == manager.state.current_scene_id
    for index, creation in enumerate(plan.creations):
        try:
            candidate, completed = _create_garment(manager, event, plan, actors, creation, index)
            _store_actor(manager, states, candidate)
            actors[creation.actor_id] = candidate
            changed = True
            accepted.append(completed)
        except ValueError as error:
            errors.append(str(error))
    for action in plan.actions:
        actor = actors.get(action.actor_id)
        if not same_scene or actor is None:
            errors.append("The character is no longer in the current location.")
            continue
        candidate = deepcopy(actor)
        try:
            item = owned_items(
                candidate["resolved_inventory"], equipment=candidate["equipment"]
            ).get(action.item_id, {})
            garment = garment_for_item(item)
            if (
                action.operation != "remove"
                and garment
                and garment.underwear
                and not _detail_allowed(candidate, manager)
            ):
                raise ValueError(
                    "Detailed garment tracking is unavailable for the current settings or known age."
                )
            _change_wear(candidate, action)
            _store_actor(manager, states, candidate)
            actors[action.actor_id] = candidate
            changed = True
            accepted.append(
                {
                    "actor_id": action.actor_id,
                    "item_id": action.item_id,
                    "operation": action.operation,
                    "uncovered_regions": action.uncovered_regions,
                }
            )
        except ValueError as error:
            errors.append(str(error))
    states[LEDGER_KEY] = {
        "version": 1,
        "processed_message_ids": (processed + [plan.message_id])[-128:],
        "created_item_ids": (
            (ledger.get("created_item_ids", []) if isinstance(ledger, dict) else [])
            + [item["item_id"] for item in accepted if "acquisition" in item]
        )[-512:],
    }
    event.narrative_description += (
        "\nAUTHORITATIVE CLOTHING RESOLUTION (internal IDs, do not print): "
        + json.dumps({"completed": accepted, "not_completed": errors}, ensure_ascii=False)
    )
    event.narrative_description += " Describe only completed clothing changes, do not convert rejected requests into successful dressing or acquisition."
    manager._vn_wardrobe_changed = changed
    return True
