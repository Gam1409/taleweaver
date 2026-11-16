"""Apply typed character and wearable completions to template data only."""

from copy import deepcopy
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.engine.authoring_clothing_policy import allows_inner_layers
from backend.engine.character_identity import identity_facts, update_identity
from backend.engine.clothing.profiles import validate_profile
from backend.engine.clothing.schema import Garment, VisualProfile, WornItem
from backend.engine.clothing.visuals import canonical_inventory
from backend.engine.personality.profile import read_profile
from backend.engine.template_avatar import template_avatar_condition
from backend.models.adventure_template import AdventureTemplate
from backend.models.avatar import Avatar
from backend.models.world_entity import WorldEntity
from backend.schemas.authoring_completion import CharacterCompletion, OutfitItem, WearableCompletion

CHARACTER_FIELDS = frozenset(CharacterCompletion.model_fields)
WEARABLE_FIELDS = frozenset(WearableCompletion.model_fields)


def _parse(model: Any, updates: dict) -> Any:
    try:
        return model.model_validate(
            {key: value for key, value in updates.items() if key in model.model_fields}
        )
    except ValidationError as exc:
        raise HTTPException(400, "Invalid structured character or clothing proposal.") from exc


def complete_wearable(item: WorldEntity, updates: dict, *, allow_inner: bool = False) -> None:
    if not WEARABLE_FIELDS.intersection(updates):
        return
    if item.item_type != "WEARABLE":
        raise HTTPException(400, "Clothing metadata can only be added to a wearable item.")
    plan = _parse(WearableCompletion, updates)
    if plan.wearable_slots and not item.wearable_slots:
        item.wearable_slots = list(plan.wearable_slots)
    if plan.clothing:
        metadata = dict(item.metadata_json or {})
        supplied = plan.clothing.model_dump()
        existing = metadata.get("clothing")
        if isinstance(existing, dict):
            supplied = _preserve_garment_facts(supplied, existing)
        checked = _parse(WearableCompletion, {"clothing": supplied})
        if checked.clothing.underwear and not allow_inner:
            raise HTTPException(
                400,
                "Inner layers require mature mode, detailed clothing and an already established adult owner.",
            )
        metadata["clothing"] = checked.clothing.model_dump()
        item.metadata_json = metadata


def _preserve_garment_facts(proposed: dict, existing: dict) -> dict:
    result = dict(proposed)
    for key, value in existing.items():
        candidate = {**result, key: value}
        try:
            Garment.model_validate(candidate)
        except ValidationError:
            continue
        result = candidate
    return result


def _owned_ids(actor: Avatar | WorldEntity) -> set[str]:
    values = list(actor.inventory or [])
    if isinstance(actor, Avatar):
        values.extend((actor.equipment or {}).values())
    return {
        str(value.get("id")) if isinstance(value, dict) else str(value) for value in values if value
    }


def _outfit_object(
    actor: Avatar | WorldEntity,
    proposal: OutfitItem,
    objects: dict[str, WorldEntity],
    owned: set[str],
    allow_inner: bool,
) -> WorldEntity:
    identifier = (
        proposal.item_id
        or "OUTFIT_"
        + uuid5(NAMESPACE_URL, f"{actor.template_id}:{actor.id}:{proposal.name.casefold()}")
        .hex[:20]
        .upper()
    )
    if not proposal.item_id:
        existing = next(
            (
                item
                for key, item in objects.items()
                if key in owned and item.name.casefold() == proposal.name.casefold()
            ),
            None,
        )
        if existing is not None:
            identifier = existing.id
    item = objects.get(identifier)
    if proposal.clothing.underwear and not allow_inner:
        raise HTTPException(
            400,
            "Inner layers require mature mode, detailed clothing and an already established adult owner.",
        )
    if item is not None:
        if identifier not in owned:
            raise HTTPException(400, "Outfit items must already belong to this character.")
        complete_wearable(
            item,
            proposal.model_dump(include={"clothing", "wearable_slots"}),
            allow_inner=allow_inner,
        )
        return item
    if proposal.item_id:
        raise HTTPException(400, "An existing outfit item could not be resolved.")
    return WorldEntity(
        id=identifier,
        template_id=actor.template_id,
        session_id=None,
        entity_type="OBJECT",
        name=proposal.name,
        description=proposal.description,
        item_type="WEARABLE",
        current_scene_id="INVENTORY",
        is_in_inventory=True,
        is_portable=True,
        wearable_slots=list(proposal.wearable_slots),
        metadata_json={"clothing": proposal.clothing.model_dump()},
    )


def _merge_appearance(actor: Any, plan: CharacterCompletion) -> VisualProfile:
    try:
        profile = VisualProfile.model_validate(actor.visual_profile or {})
    except ValidationError as exc:
        raise HTTPException(
            400, "Repair the invalid existing visual profile before adding clothing."
        ) from exc
    if actor.visual_profile is None and (
        not plan.appearance
        or not any(getattr(plan.appearance, key) for key in ("hair", "eyes", "build", "features"))
    ):
        raise HTTPException(
            400,
            "Supply appearance together with an initial outfit so existing appearance is not lost.",
        )
    if plan.appearance:
        supplied = plan.appearance.model_dump(exclude_none=True)
        established = profile.appearance.model_dump(exclude_none=True)
        supplied.update({key: value for key, value in established.items() if value != ""})
        # Age is maintained through the explicit card field, never appearance extraction.
        supplied["age_years"] = identity_facts(actor).get("age_years")
        profile.appearance = type(profile.appearance).model_validate(supplied)
    return profile


def _item_record(item: WorldEntity) -> dict:
    return {
        "id": item.id,
        "name": item.name,
        "description": item.description,
        "item_type": "WEARABLE",
        "wearable_slots": item.wearable_slots,
        "clothing": deepcopy((item.metadata_json or {}).get("clothing")),
    }


def _sync_manifest(
    adventure: AdventureTemplate, actor: Avatar | WorldEntity, items: list[WorldEntity]
) -> None:
    manifest = deepcopy(adventure.original_manifest or {})
    if isinstance(actor, Avatar):
        record = manifest.setdefault("protagonist", {})
        record["starting_inventory"] = deepcopy(actor.inventory)
        record["starting_equipment"] = deepcopy(actor.equipment)
        record["stats"] = deepcopy(actor.stats)
    else:
        records = manifest.setdefault("npcs", [])
        record = next((row for row in records if row.get("id") == actor.id), None)
        if record is None:
            record = {
                "id": actor.id,
                "name": actor.name,
                "description": actor.description,
                "current_scene_id": actor.current_scene_id,
            }
            records.append(record)
        record["inventory"] = deepcopy(actor.inventory)
        record["metadata_json"] = deepcopy(actor.metadata_json)
        record["personality_profile"] = deepcopy(
            (actor.metadata_json or {}).get("personality_profile", {})
        )
    record.update(
        name=actor.name,
        description=actor.description,
        goal=actor.goal,
        character=actor.character,
        gender=actor.gender,
        age_years=actor.age_years,
        visual_profile=deepcopy(actor.visual_profile),
    )
    records = manifest.setdefault("objects", [])
    for item in items:
        stored = next((row for row in records if row.get("id") == item.id), None)
        data = {**_item_record(item), "current_scene_id": "INVENTORY", "is_in_inventory": True}
        if stored is None:
            records.append(data)
        else:
            stored.update(data)
    adventure.original_manifest = manifest


async def complete_character(
    db: AsyncSession, adventure: AdventureTemplate, actor: Avatar | WorldEntity, updates: dict
) -> None:
    if not CHARACTER_FIELDS.intersection(updates):
        return
    if actor.template_id != adventure.id or (
        isinstance(actor, WorldEntity) and actor.session_id is not None
    ):
        raise HTTPException(400, "Only template characters can be completed.")
    allow_inner = allows_inner_layers(adventure.original_manifest, actor)
    plan: CharacterCompletion = _parse(CharacterCompletion, updates)
    # Fill explicit identity gaps; never replace a previously authored age or gender.
    identity = {
        key: getattr(plan, key)
        for key in ("gender", "age_years")
        if key in plan.model_fields_set and key not in identity_facts(actor)
    }
    update_identity(actor, CharacterCompletion.model_validate(identity))
    if plan.personality_profile and isinstance(actor, WorldEntity):
        traits = plan.personality_profile.model_dump()
        traits.update(
            {key: value for key, value in read_profile(actor).model_dump().items() if value}
        )
        actor.metadata_json = {**(actor.metadata_json or {}), "personality_profile": traits}
    if plan.outfit_exemption:
        field = "stats" if isinstance(actor, Avatar) else "metadata_json"
        setattr(
            actor,
            field,
            {**(getattr(actor, field) or {}), "outfit_exemption": plan.outfit_exemption},
        )
    if not plan.outfit and not plan.appearance:
        _sync_manifest(adventure, actor, [])
        return
    profile = _merge_appearance(actor, plan)
    rows = list(
        await db.scalars(
            select(WorldEntity).where(
                WorldEntity.template_id == adventure.id,
                WorldEntity.session_id.is_(None),
                WorldEntity.entity_type == "OBJECT",
            )
        )
    )
    objects = {row.id: row for row in rows}
    owned = _owned_ids(actor)
    inventory = deepcopy(actor.inventory or [])
    equipment = deepcopy(actor.equipment or {}) if isinstance(actor, Avatar) else {}
    affected = _apply_outfit(
        db, actor, plan, objects, owned, inventory, equipment, profile, allow_inner
    )
    actor.inventory = inventory
    if isinstance(actor, Avatar):
        actor.equipment = equipment
    try:
        validated = validate_profile(
            profile,
            canonical_inventory([*inventory, *equipment.values()], list(objects.values())),
            equipment=equipment,
        )
    except ValueError as exc:
        raise HTTPException(
            400, "Clothing completion contains invalid ownership or worn references."
        ) from exc
    actor.visual_profile = validated.model_dump()
    _sync_manifest(adventure, actor, affected)
    for item in affected:
        _sync_wearable(adventure, item, [actor])


def _apply_outfit(
    db: AsyncSession,
    actor: Avatar | WorldEntity,
    plan: CharacterCompletion,
    objects: dict[str, WorldEntity],
    owned: set[str],
    inventory: list,
    equipment: dict,
    profile: VisualProfile,
    allow_inner: bool,
) -> list[WorldEntity]:
    affected = []
    for proposal in plan.outfit:
        item = _outfit_object(actor, proposal, objects, owned, allow_inner)
        db.add(item)
        objects[item.id] = item
        if item.id not in owned:
            inventory.append(_item_record(item))
            owned.add(item.id)
        if item.id not in {worn.item_id for worn in profile.worn}:
            profile.worn.append(WornItem(item_id=item.id))
        if isinstance(actor, Avatar):
            _fill_empty_slots(item, equipment)
        affected.append(item)
    return affected


def _fill_empty_slots(item: WorldEntity, equipment: dict) -> None:
    for slot in item.wearable_slots or []:
        if not equipment.get(slot):
            equipment[slot] = _item_record(item)


async def complete_owned_wearable(
    db: AsyncSession, template_id: str, item: WorldEntity, updates: dict
) -> None:
    if not WEARABLE_FIELDS.intersection(updates):
        return
    adventure = await db.get(AdventureTemplate, template_id)
    actors = list(await db.scalars(select(Avatar).where(template_avatar_condition(template_id))))
    npcs = list(
        await db.scalars(
            select(WorldEntity).where(
                WorldEntity.template_id == template_id,
                WorldEntity.session_id.is_(None),
                WorldEntity.entity_type == "NPC",
            )
        )
    )
    candidates: list[Avatar | WorldEntity] = [*actors, *npcs]
    owners = [actor for actor in candidates if item.id in _owned_ids(actor)]
    allow_inner = bool(
        adventure
        and len(owners) == 1
        and allows_inner_layers(adventure.original_manifest, owners[0])
    )
    complete_wearable(item, updates, allow_inner=allow_inner)
    if adventure is not None:
        _sync_wearable(adventure, item, owners)


def _sync_wearable(
    adventure: AdventureTemplate, item: WorldEntity, owners: list[Avatar | WorldEntity]
) -> None:
    data = _item_record(item)

    def refresh(value: Any) -> Any:
        if isinstance(value, dict) and value.get("id") == item.id:
            return {**value, "clothing": data["clothing"], "wearable_slots": data["wearable_slots"]}
        return value

    for actor in owners:
        actor.inventory = [refresh(value) for value in actor.inventory or []]
        if isinstance(actor, Avatar):
            actor.equipment = {
                key: refresh(value) for key, value in (actor.equipment or {}).items()
            }
        _sync_manifest(adventure, actor, [])
    manifest = deepcopy(adventure.original_manifest or {})
    records = manifest.setdefault("objects", [])
    record = next((row for row in records if row.get("id") == item.id), None)
    if record is None:
        records.append(
            {
                **data,
                "current_scene_id": item.current_scene_id,
                "is_in_inventory": item.is_in_inventory,
            }
        )
    else:
        record.update(clothing=data["clothing"], wearable_slots=data["wearable_slots"])
    adventure.original_manifest = manifest
