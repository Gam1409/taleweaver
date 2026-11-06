"""Session-scoped item references are repaired together without changing possession."""

from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException

from backend.engine.chpm.kernel import digest
from backend.engine.clothing.context import resolved_inventory
from backend.engine.clothing.profiles import validate_profile
from backend.engine.item_repair_contracts import RepairApply
from backend.engine.visual_novel.continuity import _entity_item


def identifier(value: Any) -> Any:
    return value.get("id") if isinstance(value, dict) else value


def inventory(entity: Any, states: dict) -> list:
    raw = (states.get(entity.id) or {}).get(
        "inventory", entity.inventory or (entity.metadata_json or {}).get("inventory") or []
    )
    return raw if isinstance(raw, list) else []


@dataclass
class ItemContext:
    state: Any
    avatar: Any
    entities: list[Any]
    item_id: str

    def representations(self) -> list[dict]:
        result: list[dict] = []
        for owner, entries in [
            ("__player__", self.avatar.inventory or []),
            ("__equipment__", list((self.avatar.equipment or {}).values())),
        ] + [
            (entity.id, inventory(entity, self.state.entity_states or {}))
            for entity in self.entities
        ]:
            result.extend(
                {"owner": owner, "item": entry}
                for entry in entries
                if identifier(entry) == self.item_id
            )
        for entity in self.entities:
            if entity.id == self.item_id and entity.entity_type == "OBJECT":
                result.append(
                    {
                        "owner": "__world__",
                        "location": (self.state.entity_states or {})
                        .get(entity.id, {})
                        .get("current_scene_id", entity.current_scene_id),
                        "item": _entity_item(
                            entity, (self.state.entity_states or {}).get(entity.id, {})
                        ),
                    }
                )
        return result

    def read(self) -> dict:
        rows = self.representations()
        candidates = [
            row["item"] for row in rows if isinstance(row["item"], dict) and row["item"].get("name")
        ]
        if not candidates:
            raise HTTPException(404, "Item not found in this session.")
        return deepcopy(candidates[0])

    def fingerprint(self) -> str:
        import json

        return digest(json.dumps(self.representations(), ensure_ascii=False, sort_keys=True))

    def check(self, expected: str) -> None:
        if self.fingerprint() != expected:
            raise HTTPException(
                409, "The item or its owner changed. Generate a new repair preview."
            )


def _replace(entries: list, item_id: str, changes: dict, canonical: dict) -> list:
    return [
        (
            {**(entry if isinstance(entry, dict) else canonical), **changes}
            if identifier(entry) == item_id
            else entry
        )
        for entry in entries
    ]


def _changes(request: RepairApply) -> dict:
    changes = {}
    values = request.values.model_dump(mode="json")
    if "text" in request.parts:
        changes.update({key: values[key] for key in ("name", "description")})
    if "technical" in request.parts:
        changes.update(
            {key: values[key] for key in ("item_type", "is_portable", "wearable_slots", "clothing")}
        )
    if "image" in request.parts:
        changes["image_url"] = request.image_url
    return changes


def apply(context: ItemContext, request: RepairApply) -> dict:
    context.check(request.before_hash)
    old = context.read()
    changes = _changes(request)
    states = deepcopy(context.state.entity_states or {})
    avatar_inventory = _replace(context.avatar.inventory or [], context.item_id, changes, old)
    equipment = {
        slot: (
            {**entry, **changes}
            if isinstance(entry, dict) and identifier(entry) == context.item_id
            else entry
        )
        for slot, entry in (context.avatar.equipment or {}).items()
    }
    for entity in context.entities:
        entries = inventory(entity, states)
        if any(identifier(entry) == context.item_id for entry in entries):
            states[entity.id] = {
                **states.get(entity.id, {}),
                "inventory": _replace(entries, context.item_id, changes, old),
            }
    entity = next(
        (
            row
            for row in context.entities
            if row.id == context.item_id and row.entity_type == "OBJECT"
        ),
        None,
    )
    if entity:
        states[entity.id] = {
            **states.get(entity.id, {}),
            **changes,
            "vn_item_data": {**old, **changes},
        }
    if "technical" in request.parts:
        _validate_profiles(context, states, avatar_inventory, equipment)
    # Stage/validate everything before writing. No ownership, wear or scripts change.
    context.avatar.inventory = avatar_inventory
    context.avatar.equipment = equipment
    context.state.entity_states = states
    if entity:
        _update_entity(entity, changes)
    return {**old, **changes}


def _update_entity(entity: Any, changes: dict) -> None:
    for key in ("name", "description", "item_type", "is_portable", "image_url"):
        if key in changes:
            setattr(entity, key, changes[key])
    entity.metadata_json = {**(entity.metadata_json or {}), **changes}


def _validate_profiles(
    context: ItemContext, states: dict, avatar_inventory: list, equipment: dict
) -> None:
    if context.avatar.visual_profile and context.item_id in {
        identifier(row) for row in avatar_inventory + list(equipment.values())
    }:
        validate_profile(
            context.avatar.visual_profile,
            resolved_inventory(avatar_inventory, context.entities, states),
            equipment=equipment,
        )
    for entity in context.entities:
        if entity.entity_type != "NPC":
            continue
        profile = states.get(entity.id, {}).get("visual_profile", entity.visual_profile)
        if profile and any(identifier(row) == context.item_id for row in inventory(entity, states)):
            validate_profile(
                profile, resolved_inventory(inventory(entity, states), context.entities, states)
            )
