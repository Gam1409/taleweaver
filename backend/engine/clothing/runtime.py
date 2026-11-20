"""Apply validated VN wardrobe changes after canonical ownership transfers."""

import json
from copy import deepcopy
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import select

from backend.core.state_rejection_trace import reject
from backend.engine.clothing.actions import WardrobeAction
from backend.engine.clothing.body_schema import WearSource
from backend.engine.clothing.changes import mutate as change_owned_wear
from backend.engine.clothing.context import actor_records, detail_settings, resolved_inventory
from backend.engine.clothing.historical_authority import controlled, echo
from backend.engine.clothing.outcomes import record
from backend.engine.clothing.plan_sources import SourceValidation
from backend.engine.clothing.plan_sources import current as sources_current
from backend.engine.clothing.profiles import (
    garment_for_item,
    owned_items,
    reconcile_profile,
)
from backend.engine.clothing.resolution_facts import inner_details_allowed, item_facts
from backend.engine.visual_novel.continuity import PLAYER
from backend.models.world_entity import WorldEntity

LEDGER_KEY = "__vn_wardrobe__"


def _detail_allowed(actor: dict, manager: Any) -> bool:
    return inner_details_allowed(actor["visual_profile"], detail_settings(manager)["detailed"])


def _wear_allowed(manager: Any, actor: dict, action: WardrobeAction) -> bool:
    if action.operation == "remove":
        return True
    item = owned_items(actor["resolved_inventory"], equipment=actor["equipment"]).get(
        action.item_id, {}
    )
    garment = garment_for_item(item)
    return garment is None or not garment.underwear or _detail_allowed(actor, manager)


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


def _change_wear(actor: dict, action: WardrobeAction, source: WearSource | None = None) -> None:
    change_owned_wear(
        actor,
        action.item_id,
        action.operation,
        action.uncovered_regions,
        source=source,
        partially_removed=action.partially_removed,
    )


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
    manager: Any,
    event: Any,
    plan: Any,
    actors: dict,
    creation: Any,
    index: int,
    source: WearSource | None = None,
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
            source,
        )
    completed = {
        "actor_id": creation.actor_id,
        "item_id": identifier,
        "acquisition": creation.acquisition,
        "source_id": creation.source_id,
        "worn": creation.wear,
        **item_facts(item, include_inner=_detail_allowed(candidate, manager)),
    }
    return candidate, completed


def _apply_creations(
    manager: Any, event: Any, plan: Any, actors: dict, states: dict, sources: SourceValidation
) -> tuple[list[dict], list[str]]:
    accepted = []
    errors = []
    for index, creation in enumerate(plan.creations):
        if not sources.admits(plan, creation, index):
            errors.append(_source_block(manager, event, plan, creation))
            continue
        if controlled(plan, creation, creation_index=index):
            errors.append(_historical_block(manager, event, plan, creation))
            continue
        try:
            source = plan.sources.wear_source(creation) if plan.sources else None
            candidate, completed = _create_garment(
                manager, event, plan, actors, creation, index, source
            )
            _store_actor(manager, states, candidate)
            actors[creation.actor_id] = candidate
            accepted.append(completed)
            record(event, plan, creation, "applied", actor=candidate, item_id=completed["item_id"])
        except ValueError as error:
            record(event, plan, creation, "wardrobe_rejected")
            reject(
                "clothing",
                "clothing_creation_rejected",
                str(error),
                proposal=creation,
                target_id=creation.actor_id,
                source_id=getattr(creation, "source_id", None),
                current_scene_id=manager.state.current_scene_id,
                plan_scene_id=plan.scene_id,
                actor=actors.get(creation.actor_id),
                present_actor_ids=tuple(actors),
                consumed_material_ids=getattr(event, "deleted_entities", None),
            )
            errors.append(str(error))
    return accepted, errors


def _action_result(manager: Any, actor: dict, action: WardrobeAction) -> dict:
    item = owned_items(actor["resolved_inventory"], equipment=actor["equipment"]).get(
        action.item_id, {}
    )
    return {
        "actor_id": action.actor_id,
        "item_id": action.item_id,
        "operation": action.operation,
        "uncovered_regions": next(
            (
                r.get("uncovered_regions", [])
                for r in (actor["visual_profile"] or {}).get("worn", [])
                if r["item_id"] == action.item_id
            ),
            [],
        ),
        **({"partially_removed": True} if action.partially_removed else {}),
        **item_facts(item, include_inner=_detail_allowed(actor, manager)),
    }


def _historical_block(manager: Any, event: Any, plan: Any, change: Any) -> str:
    message = "The earlier command-owned narration cannot execute a new wardrobe change."
    record(event, plan, change, "historical_command_owned")
    reject(
        "clothing",
        "clothing_historical_command_owned",
        message,
        proposal=change,
        target_id=change.actor_id,
        item_id=getattr(change, "item_id", None),
        source_message_id=plan.sources.narration.message_id,
        current_scene_id=manager.state.current_scene_id,
    )
    return message


def _historical_action(
    manager: Any, event: Any, plan: Any, actor: dict, action: WardrobeAction
) -> tuple[list[dict], list[str]]:
    if not _wear_allowed(manager, actor, action) or not echo(actor, action):
        return [], [_historical_block(manager, event, plan, action)]
    # Do not call mutate: a historical echo cannot replace current command evidence.
    record(event, plan, action, "already_current", actor=actor)
    return [{**_action_result(manager, actor, action), "already_current": True}], []


def _apply_actions(
    manager: Any, event: Any, plan: Any, actors: dict, states: dict, sources: SourceValidation
) -> tuple[list[dict], list[str]]:
    accepted = []
    errors = []
    same_scene = plan.scene_id == manager.state.current_scene_id
    for action in plan.actions:
        if not sources.admits(plan, action):
            errors.append(_source_block(manager, event, plan, action))
            continue
        actor = actors.get(action.actor_id)
        if not same_scene or actor is None:
            record(event, plan, action, "actor_unavailable")
            errors.append("The character is no longer in the current location.")
            reject(
                "clothing",
                "clothing_action_rejected",
                errors[-1],
                proposal=action,
                target_id=action.actor_id,
                item_id=action.item_id,
                current_scene_id=manager.state.current_scene_id,
                plan_scene_id=plan.scene_id,
                present_actor_ids=tuple(actors),
            )
            continue
        if controlled(plan, action):
            completed, denied = _historical_action(manager, event, plan, actor, action)
            accepted.extend(completed)
            errors.extend(denied)
            continue
        candidate = deepcopy(actor)
        try:
            if not _wear_allowed(manager, candidate, action):
                raise ValueError(
                    "Detailed garment tracking is unavailable for the current settings or known age."
                )
            source = plan.sources.wear_source(action) if plan.sources else None
            _change_wear(candidate, action, source)
            _store_actor(manager, states, candidate)
            actors[action.actor_id] = candidate
            record(event, plan, action, "applied", actor=candidate)
            accepted.append(_action_result(manager, candidate, action))
        except ValueError as error:
            record(event, plan, action, "wardrobe_rejected")
            reject(
                "clothing",
                "clothing_action_rejected",
                str(error),
                proposal=action,
                target_id=action.actor_id,
                item_id=action.item_id,
                current_scene_id=manager.state.current_scene_id,
                plan_scene_id=plan.scene_id,
                actor=actor,
            )
            errors.append(str(error))
    return accepted, errors


def _source_block(manager: Any, event: Any, plan: Any, change: Any) -> str:
    message = "The saved clothing source changed before application."
    record(event, plan, change, "source_changed")
    reject(
        "clothing",
        "clothing_source_changed",
        message,
        proposal=change,
        target_id=change.actor_id,
        source_message_id=plan.message_id,
        plan_scene_id=plan.scene_id,
        current_scene_id=manager.state.current_scene_id,
    )
    return message


async def apply_wardrobe(manager: Any, event: Any, states: dict) -> bool:
    """No arbitrary NPC inventory replacement; each acquisition appends one cosmetic item."""
    entities = list(
        (
            await manager.db.scalars(
                select(WorldEntity).where(WorldEntity.session_id == manager.state.session_id)
            )
        ).all()
    )
    event._vn_wardrobe_outcomes = []
    changed = _reconcile(manager, entities, states)
    manager._vn_wardrobe_changed = changed
    plan = getattr(event, "_vn_clothing_plan", None)
    if plan is None:
        return changed
    ledger = states.get(LEDGER_KEY, {})
    processed = ledger.get("processed_message_ids", []) if isinstance(ledger, dict) else []
    if plan.message_id in processed:
        return changed
    errors = list(plan.errors)
    for change in plan.rejected:
        record(event, plan, change, "proposal_ungrounded")
    for error in plan.errors:
        reject(
            "clothing",
            "clothing_plan_error",
            error,
            proposal=plan,
            current_scene_id=manager.state.current_scene_id,
            plan_scene_id=plan.scene_id,
            source_message_id=plan.message_id,
        )
    accepted = []
    sources = await sources_current(manager, plan)
    actors = actor_records(manager, entities, states)
    creations, creation_errors = _apply_creations(manager, event, plan, actors, states, sources)
    actions, action_errors = _apply_actions(manager, event, plan, actors, states, sources)
    accepted = creations + actions
    errors += creation_errors + action_errors
    changed |= any(not row.get("already_current") for row in accepted)
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
    event.narrative_description += (
        " Describe only completed clothing changes, do not convert rejected requests into successful dressing or acquisition."
        " Item names and descriptions above are canonical for these actions. Preserve their color, material and cut;"
        " wearing, removing or adjusting a garment does not change its identity. Do not invent unspecified attributes."
    )
    manager._vn_wardrobe_changed = changed
    return True
